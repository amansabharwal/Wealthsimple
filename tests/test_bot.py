from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from options_bot import backtest, cli, data
from options_bot.config import Config
from options_bot.contracts import choose
from options_bot.positions import Book, exit_advice
from options_bot.pricing import bs_delta, bs_price
from options_bot.signals import CALL, NONE, PUT, evaluate


def frame(closes, volume=5_000_000):
    closes = np.asarray(closes, dtype=float)
    idx = pd.bdate_range(end="2026-10-23", periods=len(closes))
    return pd.DataFrame({"Open": closes, "High": closes * 1.02, "Low": closes * 0.98,
                         "Close": closes, "Volume": volume}, index=idx)


def trend_then_cross(direction):
    """Long trend, a shallow pullback, then a sharp resumption with a volume spike."""
    base = np.linspace(10, 20, 150)
    pull = np.linspace(20, 18.8, 12)
    resume = np.linspace(18.9, 19.5, 4)
    closes = np.concatenate([base, pull, resume])
    if direction == PUT:
        closes = 40 - closes
    df = frame(closes)
    df.iloc[-1, df.columns.get_loc("Volume")] = 9_000_000
    return df


@pytest.fixture
def cfg(tmp_path):
    return Config(positions_file=str(tmp_path / "pos.json"), state_file=str(tmp_path / "s.json"),
                  min_volume=1, min_open_interest=1)


def test_bullish_and_bearish_signals():
    assert evaluate("X", trend_then_cross(CALL), 4).side == CALL
    assert evaluate("X", trend_then_cross(PUT), 4).side == PUT


def test_flat_market_gives_no_signal():
    rng = np.random.default_rng(0)
    assert evaluate("X", frame(20 + rng.normal(0, 0.01, 200)), 5).side == NONE


def test_short_history_is_no_trade():
    assert evaluate("X", frame(np.linspace(10, 11, 30)), 4).side == NONE


def test_black_scholes_sanity():
    c = bs_price(100, 100, 0.25, 0.3, "CALL")
    p = bs_price(100, 100, 0.25, 0.3, "PUT")
    assert c - p == pytest.approx(100 - 100 * np.exp(-0.04 * 0.25), abs=1e-6)  # put-call parity
    assert 0.5 < bs_delta(100, 100, 0.25, 0.3, "CALL") < 0.6
    assert 0.4 < bs_delta(100, 100, 0.25, 0.3, "PUT") < 0.5


def fake_chain(spot, side):
    strikes = np.arange(spot * 0.7, spot * 1.3, 0.5)
    t = 30 / 365
    mids = np.array([bs_price(spot, k, t, 0.5, side) for k in strikes])
    return pd.DataFrame({"contractSymbol": [f"X{k:g}" for k in strikes], "strike": strikes,
                         "bid": mids * 0.97, "ask": mids * 1.03, "lastPrice": mids,
                         "volume": 500, "openInterest": 2000, "impliedVolatility": 0.5})


def test_choose_respects_budget_and_delta(cfg):
    today = date(2026, 10, 26)
    exp = today + timedelta(days=30)
    pick = choose("X", CALL, 15.0, 0.45, {exp: fake_chain(15.0, CALL)}, today, cfg)
    assert pick is not None
    assert pick.cost_usd <= cfg.max_premium_usd
    assert cfg.min_delta <= pick.delta <= cfg.max_delta
    assert pick.contracts == 1


def test_choose_returns_none_when_too_expensive(cfg):
    today = date(2026, 10, 26)
    exp = today + timedelta(days=30)
    assert choose("X", CALL, 400.0, 0.3, {exp: fake_chain(400.0, CALL)}, today, cfg) is None


def test_exit_rules(cfg):
    book = Book(cfg.positions_file)
    p = book.add("X", "call", "2026-12-18", 15, 1, 1.00, today=date(2026, 10, 26))
    d = date(2026, 10, 28)
    assert exit_advice(p, 1.55, d, cfg).action == "SELL"            # take profit
    assert exit_advice(p, 0.60, d, cfg).action == "SELL"            # stop loss
    assert exit_advice(p, 1.10, d, cfg).action == "HOLD"
    assert exit_advice(p, 1.10, d, cfg, opposite_signal=True).action == "SELL"
    assert exit_advice(p, 1.10, date(2026, 12, 10), cfg).action == "SELL"  # time stop
    p.high_water = 1.35
    assert "breakeven" in exit_advice(p, 0.98, d, cfg).reason


def test_book_roundtrip(cfg):
    book = Book(cfg.positions_file)
    p = book.add("sofi", "CALL", "2026-12-18", 15, 1, 0.80)
    Book(cfg.positions_file).close(p.id, 1.20)
    again = Book(cfg.positions_file)
    assert not again.open
    assert again.realized_pnl_usd(0.75) == pytest.approx(40 - 1.5)


def test_backtest_runs_and_tracks_equity(cfg):
    rng = np.random.default_rng(1)
    closes = 15 * np.exp(np.cumsum(rng.normal(0.0005, 0.03, 600)))
    res = backtest.run("X", frame(closes), cfg)
    assert len(res.equity_cad) > 0
    assert res.trades, "expected some trades on a volatile random walk"
    assert min(res.equity_cad) > 0
    assert "trades" in backtest.summarize("X", res, cfg)


def test_market_hours():
    from datetime import datetime
    assert cli.market_open(datetime(2026, 10, 26, 11, 0, tzinfo=cli.ET))       # Monday
    assert not cli.market_open(datetime(2026, 10, 25, 11, 0, tzinfo=cli.ET))   # Sunday
    assert not cli.market_open(datetime(2026, 10, 26, 17, 0, tzinfo=cli.ET))


def test_scan_and_check_end_to_end(cfg, monkeypatch, capsys):
    df = trend_then_cross(CALL)
    spot = float(df.Close.iloc[-1])
    exp = date.today() + timedelta(days=30)
    monkeypatch.setattr(data, "history", lambda t, d=250: df)
    monkeypatch.setattr(data, "next_earnings", lambda t: None)
    monkeypatch.setattr(data, "expirations", lambda t: [exp])
    monkeypatch.setattr(data, "chain", lambda t, e, s: fake_chain(spot, s))
    cfg.watchlist = ["X"]

    state = {}
    sent = cli.scan(cfg, state)
    assert sent and "BUY CALL" in capsys.readouterr().out
    state.update(dict.fromkeys(sent, "x"))
    assert cli.scan(cfg, state) == []  # same alert not repeated

    book = Book(cfg.positions_file)
    p = book.add("X", "CALL", exp.isoformat(), 20.0, 1, 0.50)
    monkeypatch.setattr(data, "option_quote",
                        lambda t, e, k, s: {"bid": 0.80, "ask": 0.84, "last": 0.82})
    assert cli.check(cfg) == [f"exit:{date.today()}:{p.id}"]
    assert "take profit" in capsys.readouterr().out
