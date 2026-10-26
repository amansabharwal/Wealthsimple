"""Turn indicators into BUY CALL / BUY PUT / no-trade decisions.

Each side is scored on six checks. A signal fires when the score reaches
Config.min_score and the opposite side is weak.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .indicators import add_indicators

CALL, PUT, NONE = "CALL", "PUT", "NONE"
MAX_SCORE = 6


@dataclass
class Signal:
    ticker: str
    side: str
    score: int
    price: float
    reasons: list[str] = field(default_factory=list)
    hv20: float = 0.0
    atr: float = 0.0


def _crossed_up(a: pd.Series, b: pd.Series, i: int, bars: int = 3) -> bool:
    """a is above b at bar i, and was not above it for the whole of the previous `bars` bars."""
    above = (a > b).to_numpy()
    return bool(above[i] and not above[max(0, i - bars):i].all())


def score_at(d: pd.DataFrame, i: int) -> tuple[list[str], list[str]]:
    """Bull and bear reasons at row i of a frame that already has indicators."""
    last, prev = d.iloc[i], d.iloc[i - 1]
    bull, bear = [], []

    # 1. Trend
    if last.Close > last.ema50 and last.ema21 > last.ema50:
        bull.append("uptrend (price & EMA21 above EMA50)")
    if last.Close < last.ema50 and last.ema21 < last.ema50:
        bear.append("downtrend (price & EMA21 below EMA50)")

    # 2. Fresh momentum cross in the last 3 bars
    if _crossed_up(d.ema9, d.ema21, i):
        bull.append("EMA9 crossed above EMA21")
    if _crossed_up(d.ema21, d.ema9, i):
        bear.append("EMA9 crossed below EMA21")

    # 3. RSI in a healthy zone and turning the right way (not overbought/oversold)
    if 45 <= last.rsi <= 68 and last.rsi > prev.rsi:
        bull.append(f"RSI rising ({last.rsi:.0f})")
    if 32 <= last.rsi <= 55 and last.rsi < prev.rsi:
        bear.append(f"RSI falling ({last.rsi:.0f})")

    # 4. MACD histogram positive and growing
    if last.macd_hist > 0 and last.macd_hist > prev.macd_hist:
        bull.append("MACD momentum building")
    if last.macd_hist < 0 and last.macd_hist < prev.macd_hist:
        bear.append("MACD momentum falling")

    # 5. Volume confirmation
    if last.Volume > 1.2 * last.vol_avg20:
        if last.Close > prev.Close:
            bull.append("above-average volume on an up day")
        elif last.Close < prev.Close:
            bear.append("above-average volume on a down day")

    # 6. Not overextended: within 2 ATR of the EMA21
    if abs(last.Close - last.ema21) <= 2 * last.atr:
        if last.Close > last.ema21:
            bull.append("not overextended")
        elif last.Close < last.ema21:
            bear.append("not overextended")

    return bull, bear


def decide(ticker: str, d: pd.DataFrame, i: int, min_score: int) -> Signal:
    bull, bear = score_at(d, i)
    row = d.iloc[i]
    common = dict(price=float(row.Close), hv20=float(row.hv20), atr=float(row.atr))
    if len(bull) >= min_score and len(bear) <= 1:
        return Signal(ticker, CALL, len(bull), reasons=bull, **common)
    if len(bear) >= min_score and len(bull) <= 1:
        return Signal(ticker, PUT, len(bear), reasons=bear, **common)
    return Signal(ticker, NONE, max(len(bull), len(bear)),
                  reasons=[f"bull {len(bull)}/{MAX_SCORE}, bear {len(bear)}/{MAX_SCORE}"], **common)


def evaluate(ticker: str, df: pd.DataFrame, min_score: int) -> Signal:
    if len(df) < 60:
        price = float(df["Close"].iloc[-1]) if len(df) else 0.0
        return Signal(ticker, NONE, 0, price, ["not enough history"])
    d = add_indicators(df)
    return decide(ticker, d, len(d) - 1, min_score)
