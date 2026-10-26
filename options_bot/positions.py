"""Track the options you actually bought on Wealthsimple and decide when to sell."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from .config import Config


@dataclass
class Position:
    id: int
    ticker: str
    side: str
    expiry: str          # ISO date
    strike: float
    contracts: int
    entry_price: float   # per-share premium you paid (e.g. 0.85 = $85/contract)
    opened: str
    high_water: float = 0.0
    closed: str = ""
    exit_price: float = 0.0

    @property
    def expiry_date(self) -> date:
        return date.fromisoformat(self.expiry)

    def label(self) -> str:
        return f"#{self.id} {self.ticker} {self.expiry} ${self.strike:g} {self.side} x{self.contracts}"


@dataclass
class ExitAdvice:
    action: str   # "SELL" or "HOLD"
    reason: str
    pnl_pct: float


def exit_advice(p: Position, price: float, today: date, cfg: Config,
                opposite_signal: bool = False) -> ExitAdvice:
    """price is the current per-share value (use the bid: that's what you can sell at)."""
    pnl = price / p.entry_price - 1
    high = max(p.high_water, price)
    dte = (p.expiry_date - today).days
    if pnl >= cfg.take_profit_pct:
        return ExitAdvice("SELL", f"take profit hit (+{pnl:.0%})", pnl)
    if pnl <= -cfg.stop_loss_pct:
        return ExitAdvice("SELL", f"stop loss hit ({pnl:.0%})", pnl)
    if high / p.entry_price - 1 >= cfg.breakeven_trigger_pct and price <= p.entry_price:
        return ExitAdvice("SELL", "gave back gains: breakeven stop", pnl)
    if dte <= cfg.exit_dte:
        return ExitAdvice("SELL", f"only {dte} days to expiry: time decay accelerating", pnl)
    if opposite_signal:
        return ExitAdvice("SELL", "trend reversed against the position", pnl)
    return ExitAdvice("HOLD", f"P/L {pnl:+.0%}, {dte} DTE", pnl)


class Book:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        raw = json.loads(self.path.read_text()) if self.path.exists() else []
        self.positions = [Position(**r) for r in raw]

    def save(self) -> None:
        self.path.write_text(json.dumps([asdict(p) for p in self.positions], indent=2))

    @property
    def open(self) -> list[Position]:
        return [p for p in self.positions if not p.closed]

    def add(self, ticker: str, side: str, expiry: str, strike: float, contracts: int,
            entry_price: float, today: date | None = None) -> Position:
        side = side.upper()
        if side not in ("CALL", "PUT"):
            raise ValueError("side must be CALL or PUT")
        date.fromisoformat(expiry)
        pid = max((p.id for p in self.positions), default=0) + 1
        p = Position(pid, ticker.upper(), side, expiry, strike, contracts, entry_price,
                     (today or date.today()).isoformat(), high_water=entry_price)
        self.positions.append(p)
        self.save()
        return p

    def close(self, pid: int, exit_price: float, today: date | None = None) -> Position:
        p = self.get(pid)
        p.closed = (today or date.today()).isoformat()
        p.exit_price = exit_price
        self.save()
        return p

    def get(self, pid: int) -> Position:
        for p in self.positions:
            if p.id == pid:
                return p
        raise KeyError(f"no position #{pid}")

    def realized_pnl_usd(self, fee: float) -> float:
        return sum((p.exit_price - p.entry_price) * 100 * p.contracts - 2 * fee * p.contracts
                   for p in self.positions if p.closed)
