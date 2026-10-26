"""Technical indicators on a pandas OHLCV frame (columns: Open, High, Low, Close, Volume)."""

from __future__ import annotations

import numpy as np
import pandas as pd


def ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(100)


def macd_hist(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.Series:
    line = ema(close, fast) - ema(close, slow)
    return line - ema(line, signal)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev = df["Close"].shift()
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev).abs(),
        (df["Low"] - prev).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def historical_vol(close: pd.Series, window: int = 20) -> pd.Series:
    """Annualized close-to-close volatility."""
    return np.log(close / close.shift()).rolling(window).std() * np.sqrt(252)


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    c = out["Close"]
    out["ema9"] = ema(c, 9)
    out["ema21"] = ema(c, 21)
    out["ema50"] = ema(c, 50)
    out["rsi"] = rsi(c)
    out["macd_hist"] = macd_hist(c)
    out["atr"] = atr(out)
    out["hv20"] = historical_vol(c)
    out["vol_avg20"] = out["Volume"].rolling(20).mean()
    return out
