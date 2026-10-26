"""Black-Scholes price and delta (used to estimate delta and for the backtest)."""

from __future__ import annotations

import math

RISK_FREE = 0.04


def _ncdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _d1_d2(s: float, k: float, t: float, vol: float, r: float) -> tuple[float, float]:
    d1 = (math.log(s / k) + (r + 0.5 * vol * vol) * t) / (vol * math.sqrt(t))
    return d1, d1 - vol * math.sqrt(t)


def bs_price(s: float, k: float, t: float, vol: float, side: str, r: float = RISK_FREE) -> float:
    if t <= 0 or vol <= 0:
        return max(0.0, s - k) if side == "CALL" else max(0.0, k - s)
    d1, d2 = _d1_d2(s, k, t, vol, r)
    if side == "CALL":
        return s * _ncdf(d1) - k * math.exp(-r * t) * _ncdf(d2)
    return k * math.exp(-r * t) * _ncdf(-d2) - s * _ncdf(-d1)


def bs_delta(s: float, k: float, t: float, vol: float, side: str, r: float = RISK_FREE) -> float:
    """Absolute delta (0..1) for both calls and puts."""
    if t <= 0 or vol <= 0:
        itm = s > k if side == "CALL" else s < k
        return 1.0 if itm else 0.0
    d1, _ = _d1_d2(s, k, t, vol, r)
    return _ncdf(d1) if side == "CALL" else 1 - _ncdf(d1)
