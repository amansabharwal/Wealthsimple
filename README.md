# Wealthsimple Options Signal Bot

A Python tool that scans stocks, tells you **when to buy a call or put**, picks a
**specific affordable contract**, and then watches your position and tells you
**when to sell**. You place the trades yourself in the Wealthsimple app.

> **Read this first.** This is an educational tool, not financial advice.
> Buying short-term options is one of the fastest ways to lose money: most
> retail options buyers lose, and an option can go to $0. This bot can't predict
> the market. What it does is enforce a plan (small positions, a stop loss, a
> profit target, a time limit) so a bad trade costs you $50–$70, not your whole
> account. Only use money you can afford to lose entirely.

## Why it doesn't place trades for you

Wealthsimple has no public trading API. Unofficial API libraries log in with your
password and break Wealthsimple's terms of service, which can get your account
locked, and they mean giving a script your credentials. So the bot **alerts** and
you **tap buy/sell**. That takes about 30 seconds per trade.

## What it does

| Step | What happens |
|---|---|
| **Scan** | For each stock on your watchlist, score 6 bullish and 6 bearish checks: trend (EMA 21/50), fresh EMA 9/21 cross, RSI, MACD momentum, volume, not overextended. 4 or more out of 6 on one side, with the other side weak, means a signal. |
| **Filter** | Skip stocks with earnings in the next 14 days (IV crush), thinly traded stocks, and options priced far above the stock's realized volatility. |
| **Pick contract** | Expiry 21–45 days out, delta about 0.55, open interest ≥ 100, bid/ask spread ≤ 15%, cost ≤ 20% of your account (about US$144 on C$1,000). Always **1 contract**. |
| **Manage** | SELL alert at +50% (take profit), −35% (stop loss), breakeven after being up 30%, 10 days before expiry, or when the trend flips. |
| **Alert** | Terminal, plus optional phone push (ntfy, free), Discord, or Telegram. |

With C$1,000 the bot allows at most 2 open positions. A typical loss is about
C$50–70 per trade, so a losing streak can't wipe you out in a week.

## Setup (on your computer; needs Python 3.10+)

```bash
git clone <this repo> && cd Wealthsimple
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp config.example.json config.json                  # then edit it
```

In `config.json`, check at least:

- `fee_per_contract_usd`: look up Wealthsimple's current options fee and update it.
- `use_usd_account`: set to `true` if you hold USD (Wealthsimple Plus/USD account).
  Otherwise each trade pays about 1.5% FX conversion on the way in and out.
- `ntfy_topic`: choose a random name like `my-options-7f3k2`, install the **ntfy**
  app on your phone, and subscribe to that topic to get push alerts.
- `watchlist`: liquid stocks whose options fit a small budget. Expensive stocks
  (TSLA, NVDA, SPY) usually have contracts above your budget and get skipped.

## Daily use

```bash
python bot.py backtest            # 1. FIRST: see how the rules did over ~3 years
python bot.py scan                # look for BUY signals right now
python bot.py watch               # or leave it running: scans + checks every 15 min, market hours only
```

When you get a BUY alert:

1. In Wealthsimple, open the stock, then **Options**, then the expiry and strike from the alert.
2. Use a **limit order** at about the mid price shown. Never use a market order on options.
3. Record what you paid: `python bot.py bought SOFI CALL 2026-12-18 15 0.85`

When you get a SELL alert, sell with a limit order near the bid, then record it:

```bash
python bot.py sold 1 1.30
python bot.py positions           # history + realized P/L
python bot.py check               # one-off check of open positions
```

## How to actually use this responsibly

1. **Backtest first.** Run `python bot.py backtest`. Option prices in the backtest
   are modelled, not real quotes, so treat it as a rough check. If it loses money
   on a ticker, take that ticker off your watchlist.
2. **Paper-trade for 2–4 weeks.** Record trades with `bought`/`sold` without
   spending real money, and see whether the alerts would have made money *after*
   fees.
3. **Then go small.** Follow every stop loss. Don't add to losing trades. Don't
   raise `max_premium_pct` after a loss to "win it back".
4. **Taxes.** In a TFSA, frequent trading can get the CRA to treat it as a
   business, and gains become taxable. In a personal (non-registered) account,
   gains are taxable, and losses can offset other gains. Wealthsimple only allows
   buying calls/puts in registered accounts.

On randomly generated price data (no real trend to find), the strategy *loses*
money: spreads, fees, FX and time decay eat away at it. That is what happens to
any options strategy without a real edge. The stop loss and position size limits
are what keep the losses small.

## Tests

```bash
pip install -r requirements-dev.txt && pytest
```

## Files

```
bot.py                   entry point
options_bot/config.py    all settings and defaults
options_bot/signals.py   buy/sell scoring rules
options_bot/contracts.py picks a liquid, affordable contract
options_bot/positions.py tracks your trades and exit rules
options_bot/backtest.py  approximate historical test
options_bot/notify.py    phone/Discord/Telegram alerts
options_bot/data.py      Yahoo Finance data (free, ~15 min delayed)
```
