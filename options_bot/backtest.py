"""Approximate backtest of the strategy on past daily prices.

Real historical option quotes aren't free, so option prices are *modelled* with
Black-Scholes using realized volatility plus a premium, and a bid/ask spread is
charged on entry and exit. Treat results as a rough sanity check, not a promise.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .config import Config
from .indicators import add_indicators
from .positions import Position, exit_advice
from .pricing import bs_delta, bs_price
from .signals import CALL, NONE, PUT, decide

IV_PREMIUM = 1.15     # options usually trade above realized vol
SPREAD_COST = 0.04    # pay ~4% of mid crossing the spread each way
ENTRY_DTE = 35


@dataclass
class Trade:
    ticker: str
    side: str
    entry_day: pd.Timestamp
    exit_day: pd.Timestamp
    entry: float
    exit: float
    reason: str

    @property
    def ret(self) -> float:
        return self.exit / self.entry - 1


@dataclass
class Result:
    trades: list[Trade] = field(default_factory=list)
    equity_cad: list[float] = field(default_factory=list)

    @property
    def win_rate(self) -> float:
        return sum(t.ret > 0 for t in self.trades) / len(self.trades) if self.trades else 0.0

    @property
    def max_drawdown(self) -> float:
        peak, dd = 0.0, 0.0
        for e in self.equity_cad:
            peak = max(peak, e)
            dd = min(dd, e / peak - 1)
        return dd


def _strike_for_delta(s: float, t: float, vol: float, side: str, target: float) -> float:
    step = 0.5 if s < 25 else 1.0 if s < 100 else 5.0
    strikes = [k for k in (round(s / step) * step + j * step for j in range(-15, 16)) if k > 0]
    return min(strikes, key=lambda k: abs(bs_delta(s, k, t, vol, side) - target))


def run(ticker: str, df: pd.DataFrame, cfg: Config) -> Result:
    d = add_indicators(df).dropna()
    res = Result()
    equity = cfg.account_cad
    pos: dict | None = None
    fee_cad = cfg.fee_per_contract_usd * cfg.usd_cad
    fx = 0 if cfg.use_usd_account else cfg.fx_fee_pct

    for i in range(1, len(d)):
        day, s = d.index[i], float(d.Close.iloc[i])
        vol = max(float(d.hv20.iloc[i]) * IV_PREMIUM, 0.15)
        sig = decide(ticker, d, i, cfg.min_score)

        if pos:
            t = max((pos["expiry"] - day).days, 0) / 365
            mid = bs_price(s, pos["strike"], t, vol, pos["side"])
            bid = mid * (1 - SPREAD_COST)
            p: Position = pos["p"]
            opposite = sig.side not in (NONE, p.side)
            adv = exit_advice(p, bid, day.date(), cfg, opposite_signal=opposite)
            p.high_water = max(p.high_water, bid)
            if adv.action == "SELL":
                proceeds = bid * 100 * (1 - fx) * cfg.usd_cad - fee_cad
                equity += proceeds
                res.trades.append(Trade(ticker, p.side, pos["entry_day"], day, p.entry_price, bid,
                                        adv.reason))
                pos = None

        elif sig.side in (CALL, PUT):
            t = ENTRY_DTE / 365
            strike = _strike_for_delta(s, t, vol, sig.side, cfg.target_delta)
            ask = bs_price(s, strike, t, vol, sig.side) * (1 + SPREAD_COST)
            cost_cad = (ask * 100 * cfg.usd_cad) * (1 + fx) + fee_cad
            budget = equity * cfg.max_premium_pct
            if 0.05 < ask and cost_cad <= max(budget, 0):
                equity -= cost_cad
                expiry = day + pd.Timedelta(days=ENTRY_DTE)
                p = Position(0, ticker, sig.side, expiry.date().isoformat(), strike, 1, ask,
                             day.date().isoformat(), high_water=ask)
                pos = {"p": p, "strike": strike, "side": sig.side, "expiry": expiry,
                       "entry_day": day}

        mark = 0.0
        if pos:
            t = max((pos["expiry"] - day).days, 0) / 365
            mark = bs_price(s, pos["strike"], t, vol, pos["side"]) * 100 * cfg.usd_cad
        res.equity_cad.append(equity + mark)
    return res


def summarize(ticker: str, r: Result, cfg: Config) -> str:
    if not r.trades:
        return f"{ticker}: no trades (signals never fired or contracts too expensive for budget)"
    avg = sum(t.ret for t in r.trades) / len(r.trades)
    end = r.equity_cad[-1]
    lines = [
        f"{ticker}: {len(r.trades)} trades | win rate {r.win_rate:.0%} | avg trade {avg:+.0%} | "
        f"C${cfg.account_cad:.0f} -> C${end:.0f} ({end / cfg.account_cad - 1:+.0%}) | "
        f"max drawdown {r.max_drawdown:.0%}",
    ]
    for t in r.trades[-5:]:
        lines.append(f"    {t.entry_day:%Y-%m-%d} -> {t.exit_day:%Y-%m-%d} {t.side:4} "
                     f"{t.ret:+.0%}  {t.reason}")
    return "\n".join(lines)
