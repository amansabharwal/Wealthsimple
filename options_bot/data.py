"""Market data from Yahoo Finance (free, ~15 min delayed for options quotes).

Everything that touches the network lives here so the rest can be tested offline.
"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd


def _yf():
    try:
        import yfinance as yf
    except ImportError as e:  # pragma: no cover
        raise SystemExit("yfinance is missing. Run: pip install -r requirements.txt") from e
    return yf


def history(ticker: str, days: int = 250) -> pd.DataFrame:
    df = _yf().Ticker(ticker).history(period=f"{max(days, 60) + 120}d", interval="1d",
                                       auto_adjust=True)
    return df[["Open", "High", "Low", "Close", "Volume"]].dropna().tail(days)


def usd_cad() -> float | None:
    try:
        df = _yf().Ticker("CAD=X").history(period="5d")
        return float(df["Close"].iloc[-1])
    except Exception:
        return None


def expirations(ticker: str) -> list[date]:
    return [datetime.strptime(e, "%Y-%m-%d").date() for e in _yf().Ticker(ticker).options]


def chain(ticker: str, expiry: date, side: str) -> pd.DataFrame:
    """Columns: contractSymbol, strike, bid, ask, lastPrice, volume, openInterest, impliedVolatility."""
    oc = _yf().Ticker(ticker).option_chain(expiry.isoformat())
    df = oc.calls if side == "CALL" else oc.puts
    return df.fillna({"volume": 0, "openInterest": 0, "bid": 0, "ask": 0})


def next_earnings(ticker: str) -> date | None:
    try:
        cal = _yf().Ticker(ticker).calendar
        dates = cal.get("Earnings Date") if isinstance(cal, dict) else None
        if dates:
            d = dates[0]
            return d.date() if isinstance(d, datetime) else d
    except Exception:
        pass
    return None


def option_quote(ticker: str, expiry: date, strike: float, side: str) -> dict | None:
    df = chain(ticker, expiry, side)
    row = df[(df["strike"] - strike).abs() < 1e-6]
    if row.empty:
        return None
    r = row.iloc[0]
    return {"bid": float(r.bid), "ask": float(r.ask), "last": float(r.lastPrice)}
