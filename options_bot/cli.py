"""Command-line entry point. Run `python bot.py --help`."""

from __future__ import annotations

import argparse
import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import backtest, data, notify
from .config import Config
from .contracts import candidate_expiries, choose
from .positions import Book, exit_advice
from .signals import NONE, evaluate

ET = ZoneInfo("America/New_York")

DISCLAIMER = (
    "Signals are educational, not financial advice. Most short-term options buyers lose money. "
    "Only trade what you can afford to lose entirely."
)


def _refresh_fx(cfg: Config) -> None:
    rate = data.usd_cad()
    if rate:
        cfg.usd_cad = rate


def _load_state(cfg: Config) -> dict:
    p = Path(cfg.state_file)
    return json.loads(p.read_text()) if p.exists() else {}


def _save_state(cfg: Config, state: dict) -> None:
    Path(cfg.state_file).write_text(json.dumps(state, indent=2))


def scan(cfg: Config, alert_once: dict | None = None) -> list[str]:
    """Look for new entries. Returns the alert keys it sent."""
    book = Book(cfg.positions_file)
    held = {p.ticker for p in book.open}
    slots = cfg.max_open_positions - len(book.open)
    today = date.today()
    sent = []
    print(f"Scanning {len(cfg.watchlist)} tickers | budget per trade ~US${cfg.max_premium_usd:.0f} "
          f"| open positions {len(book.open)}/{cfg.max_open_positions}")

    for ticker in cfg.watchlist:
        try:
            df = data.history(ticker, cfg.lookback_days)
        except Exception as e:
            print(f"  {ticker:6} data error: {e}")
            continue
        if df.empty or df["Volume"].tail(20).mean() < cfg.min_avg_volume:
            print(f"  {ticker:6} skipped: low stock volume")
            continue
        sig = evaluate(ticker, df, cfg.min_score)
        if sig.side == NONE:
            print(f"  {ticker:6} ${sig.price:<8.2f} no trade ({sig.reasons[0]})")
            continue
        if ticker in held:
            print(f"  {ticker:6} {sig.side} signal but you already hold it")
            continue

        earn = data.next_earnings(ticker)
        if earn and 0 <= (earn - today).days <= cfg.skip_earnings_within_days:
            print(f"  {ticker:6} {sig.side} signal skipped: earnings on {earn} (IV crush risk)")
            continue

        try:
            exps = candidate_expiries(data.expirations(ticker), today, cfg)
            chains = {e: data.chain(ticker, e, sig.side) for e in exps}
        except Exception as e:
            print(f"  {ticker:6} option chain error: {e}")
            continue
        pick = choose(ticker, sig.side, sig.price, sig.hv20, chains, today, cfg)
        if not pick:
            print(f"  {ticker:6} {sig.side} signal, but no liquid contract fits the "
                  f"US${cfg.max_premium_usd:.0f} budget")
            continue

        key = f"entry:{today}:{ticker}:{sig.side}"
        if alert_once is not None and key in alert_once:
            continue
        stop = pick.mid * (1 - cfg.stop_loss_pct)
        target = pick.mid * (1 + cfg.take_profit_pct)
        body = "\n".join([
            f"BUY {pick.describe()}",
            f"Stock ${sig.price:.2f} | score {sig.score}/6: " + "; ".join(sig.reasons),
            f"Plan: sell at ${target:.2f} (+{cfg.take_profit_pct:.0%}) or ${stop:.2f} "
            f"(-{cfg.stop_loss_pct:.0%}), or by {pick.expiry - timedelta(days=cfg.exit_dte)}.",
            *([f"WARNING: {pick.warning}"] if pick.warning else []),
            *([f"NOTE: you already have {len(book.open)} open positions (max "
               f"{cfg.max_open_positions}); skip this unless you close one."] if slots <= 0 else []),
            f"After buying, record it: python bot.py bought {ticker} {pick.side} "
            f"{pick.expiry} {pick.strike:g} <price-you-paid>",
        ])
        notify.send(cfg, f"BUY {sig.side}: {ticker}", body)
        sent.append(key)
    return sent


def check(cfg: Config, alert_once: dict | None = None) -> list[str]:
    """Check open positions for exit signals."""
    book = Book(cfg.positions_file)
    today = date.today()
    sent = []
    if not book.open:
        print("No open positions. Record one with: python bot.py bought ...")
    for p in book.open:
        try:
            q = data.option_quote(p.ticker, p.expiry_date, p.strike, p.side)
            sig = evaluate(p.ticker, data.history(p.ticker, cfg.lookback_days), cfg.min_score)
        except Exception as e:
            print(f"  {p.label()} data error: {e}")
            continue
        if not q:
            print(f"  {p.label()} no quote found")
            continue
        price = q["bid"] if q["bid"] > 0 else q["last"]
        adv = exit_advice(p, price, today, cfg,
                          opposite_signal=sig.side not in (NONE, p.side))
        p.high_water = max(p.high_water, price)
        print(f"  {p.label()} paid {p.entry_price:.2f} now {price:.2f} -> {adv.action}: {adv.reason}")
        if adv.action == "SELL":
            key = f"exit:{today}:{p.id}"
            if alert_once is not None and key in alert_once:
                continue
            notify.send(cfg, f"SELL: {p.ticker} {p.side}",
                        f"SELL {p.label()} at ~${price:.2f} (limit near bid {q['bid']:.2f} / "
                        f"ask {q['ask']:.2f})\nReason: {adv.reason}\n"
                        f"After selling, record it: python bot.py sold {p.id} <price-you-got>")
            sent.append(key)
    book.save()
    return sent


def market_open(now: datetime | None = None) -> bool:
    now = (now or datetime.now(ET)).astimezone(ET)
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return 9 * 60 + 45 <= minutes <= 15 * 60 + 50  # skip the volatile first/last minutes


def watch(cfg: Config) -> None:
    print(f"Watching every {cfg.poll_minutes} min during US market hours. Ctrl+C to stop.")
    while True:
        if market_open():
            _refresh_fx(cfg)
            state = _load_state(cfg)
            for key in check(cfg, state) + scan(cfg, state):
                state[key] = datetime.now(ET).isoformat()
            _save_state(cfg, state)
        else:
            print(f"{datetime.now(ET):%a %H:%M} ET: market closed, waiting...")
        time.sleep(cfg.poll_minutes * 60)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="bot.py", description="Options signal bot for Wealthsimple. "
                                 + DISCLAIMER)
    ap.add_argument("--config", default="config.json")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan", help="look for new BUY signals now")
    sub.add_parser("check", help="check your open positions for SELL signals")
    sub.add_parser("watch", help="run scan + check on a loop during market hours")
    sub.add_parser("positions", help="list positions and realized P/L")
    b = sub.add_parser("bought", help="record an option you bought on Wealthsimple")
    b.add_argument("ticker")
    b.add_argument("side", choices=["CALL", "PUT", "call", "put"])
    b.add_argument("expiry", help="YYYY-MM-DD")
    b.add_argument("strike", type=float)
    b.add_argument("price", type=float, help="premium per share you paid, e.g. 0.85")
    b.add_argument("--contracts", type=int, default=1)
    s = sub.add_parser("sold", help="record that you sold a position")
    s.add_argument("id", type=int)
    s.add_argument("price", type=float)
    bt = sub.add_parser("backtest", help="test the strategy on past prices")
    bt.add_argument("tickers", nargs="*")
    bt.add_argument("--days", type=int, default=750)
    args = ap.parse_args(argv)

    cfg = Config.load(args.config)
    print(DISCLAIMER + "\n")

    if args.cmd in ("scan", "check"):
        _refresh_fx(cfg)
        (scan if args.cmd == "scan" else check)(cfg)
    elif args.cmd == "watch":
        watch(cfg)
    elif args.cmd == "bought":
        p = Book(cfg.positions_file).add(args.ticker, args.side, args.expiry, args.strike,
                                         args.contracts, args.price)
        print(f"Recorded {p.label()} @ {p.entry_price:.2f}. Run `python bot.py check` or `watch`.")
    elif args.cmd == "sold":
        p = Book(cfg.positions_file).close(args.id, args.price)
        pnl = (p.exit_price - p.entry_price) * 100 * p.contracts
        print(f"Closed {p.label()}: {p.entry_price:.2f} -> {p.exit_price:.2f} (US${pnl:+.0f})")
    elif args.cmd == "positions":
        book = Book(cfg.positions_file)
        for p in book.positions:
            status = f"closed {p.closed} @ {p.exit_price:.2f}" if p.closed else "OPEN"
            print(f"  {p.label()} paid {p.entry_price:.2f} on {p.opened} | {status}")
        print(f"Realized P/L after fees: US${book.realized_pnl_usd(cfg.fee_per_contract_usd):+.2f}")
    elif args.cmd == "backtest":
        for t in args.tickers or cfg.watchlist:
            try:
                df = data.history(t, args.days)
            except Exception as e:
                print(f"{t}: data error: {e}")
                continue
            print(backtest.summarize(t, backtest.run(t, df, cfg), cfg))
