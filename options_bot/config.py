"""Bot settings. Override any field by putting it in config.json (see config.example.json)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


@dataclass
class Config:
    # --- Account ---
    account_cad: float = 1000.0
    usd_cad: float = 1.37  # refreshed from market data at runtime when available
    # Wealthsimple options are US-listed and settle in USD. Buying from a CAD
    # account pays an FX conversion fee on the way in AND out.
    use_usd_account: bool = False
    fx_fee_pct: float = 0.015
    # Per-contract fee in USD. Check Wealthsimple's current pricing page and update.
    fee_per_contract_usd: float = 0.75

    # --- Risk ---
    max_premium_pct: float = 0.20      # never spend more than 20% of the account on one trade
    max_open_positions: int = 2
    take_profit_pct: float = 0.50      # sell when the option is up 50%
    stop_loss_pct: float = 0.35        # sell when the option is down 35%
    breakeven_trigger_pct: float = 0.30  # once up 30%, move the stop to breakeven
    exit_dte: int = 10                 # sell when this few days to expiry remain (time decay speeds up)

    # --- Contract selection ---
    min_dte: int = 21
    max_dte: int = 45
    target_delta: float = 0.55
    min_delta: float = 0.40
    max_delta: float = 0.70
    min_open_interest: int = 100
    min_volume: int = 10
    max_spread_pct: float = 0.15       # (ask - bid) / mid
    max_iv_to_hv: float = 1.6          # skip when options are priced far above realized volatility
    skip_earnings_within_days: int = 14

    # --- Signals ---
    watchlist: list[str] = field(default_factory=lambda: [
        "SOFI", "F", "PLTR", "AMD", "INTC", "NIO", "BAC", "T", "SNAP", "RIVN",
    ])
    min_score: int = 4                 # out of 6; higher = fewer but stronger signals
    min_avg_volume: int = 2_000_000
    lookback_days: int = 250

    # --- Watch mode / alerts ---
    poll_minutes: int = 15
    ntfy_topic: str = ""               # free phone push alerts via https://ntfy.sh
    discord_webhook: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    positions_file: str = "positions.json"
    state_file: str = ".bot_state.json"

    @property
    def max_premium_usd(self) -> float:
        budget_usd = self.account_cad * self.max_premium_pct / self.usd_cad
        if not self.use_usd_account:
            budget_usd /= 1 + self.fx_fee_pct
        return budget_usd

    @classmethod
    def load(cls, path: str | Path = "config.json") -> "Config":
        path = Path(path)
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text())
        known = {f.name for f in fields(cls)}
        unknown = set(raw) - known
        if unknown:
            raise ValueError(f"Unknown config keys in {path}: {sorted(unknown)}")
        return cls(**raw)

    def to_dict(self) -> dict:
        return asdict(self)
