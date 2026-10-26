"""Pick a specific, affordable, liquid option contract for a signal."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from .config import Config
from .pricing import bs_delta


@dataclass
class Pick:
    ticker: str
    side: str
    expiry: date
    strike: float
    bid: float
    ask: float
    delta: float
    iv: float
    dte: int
    contracts: int
    cost_usd: float      # premium + fees, what leaves the account
    cost_cad: float
    contract_symbol: str = ""
    warning: str = ""

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2

    def describe(self) -> str:
        return (f"{self.ticker} {self.expiry:%b %d %Y} ${self.strike:g} {self.side} "
                f"x{self.contracts}  limit ${self.mid:.2f} (bid {self.bid:.2f} / ask {self.ask:.2f})  "
                f"delta {self.delta:.2f}  IV {self.iv:.0%}  {self.dte} DTE  "
                f"cost ~US${self.cost_usd:.0f} / C${self.cost_cad:.0f}")


def candidate_expiries(expiries: list[date], today: date, cfg: Config) -> list[date]:
    return [e for e in expiries if cfg.min_dte <= (e - today).days <= cfg.max_dte]


def rank_chain(df: pd.DataFrame, spot: float, dte: int, side: str, cfg: Config) -> pd.DataFrame:
    """Filter a chain down to tradeable contracts and score them (lower score = better)."""
    if df.empty:
        return df
    df = df[(df["bid"] > 0) & (df["ask"] > df["bid"])].copy()
    if df.empty:
        return df
    t = dte / 365
    df["mid"] = (df["bid"] + df["ask"]) / 2
    df["spread_pct"] = (df["ask"] - df["bid"]) / df["mid"]
    df["delta"] = [bs_delta(spot, k, t, max(iv, 0.01), side)
                   for k, iv in zip(df["strike"], df["impliedVolatility"])]
    df["unit_cost"] = df["mid"] * 100 + cfg.fee_per_contract_usd
    df = df[
        (df["openInterest"] >= cfg.min_open_interest)
        & (df["volume"] >= cfg.min_volume)
        & (df["spread_pct"] <= cfg.max_spread_pct)
        & (df["delta"].between(cfg.min_delta, cfg.max_delta))
        & (df["unit_cost"] <= cfg.max_premium_usd)
    ].copy()
    df["rank"] = (df["delta"] - cfg.target_delta).abs() + df["spread_pct"]
    return df.sort_values("rank")


def choose(ticker: str, side: str, spot: float, hv20: float, chains: dict[date, pd.DataFrame],
           today: date, cfg: Config) -> Pick | None:
    best: tuple[float, date, pd.Series] | None = None
    for expiry, df in chains.items():
        dte = (expiry - today).days
        ranked = rank_chain(df, spot, dte, side, cfg)
        if ranked.empty:
            continue
        row = ranked.iloc[0]
        if best is None or row["rank"] < best[0]:
            best = (row["rank"], expiry, row)
    if best is None:
        return None
    _, expiry, row = best
    dte = (expiry - today).days
    n = 1  # with a small account, one contract per idea keeps losses survivable
    cost_usd = row["unit_cost"] * n
    fx = 1 if cfg.use_usd_account else 1 + cfg.fx_fee_pct
    iv = float(row["impliedVolatility"])
    warning = ""
    if hv20 > 0 and iv > cfg.max_iv_to_hv * hv20:
        warning = f"options look expensive (IV {iv:.0%} vs 20-day realized {hv20:.0%})"
    return Pick(
        ticker=ticker, side=side, expiry=expiry, strike=float(row["strike"]),
        bid=float(row["bid"]), ask=float(row["ask"]), delta=float(row["delta"]), iv=iv,
        dte=dte, contracts=n, cost_usd=cost_usd, cost_cad=cost_usd * cfg.usd_cad * fx,
        contract_symbol=str(row.get("contractSymbol", "")), warning=warning,
    )
