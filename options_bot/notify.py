"""Send alerts to the console and optionally to your phone (ntfy), Discord, or Telegram."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

from .config import Config


def _post(url: str, data: bytes, headers: dict[str, str]) -> None:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    urllib.request.urlopen(req, timeout=10).read()


def send(cfg: Config, title: str, body: str) -> None:
    print(f"\n=== {title} ===\n{body}\n", flush=True)
    targets = []
    if cfg.ntfy_topic:
        targets.append(("ntfy", lambda: _post(
            f"https://ntfy.sh/{urllib.parse.quote(cfg.ntfy_topic)}", body.encode(),
            {"Title": title.encode("ascii", "ignore").decode(), "Priority": "high"})))
    if cfg.discord_webhook:
        targets.append(("discord", lambda: _post(
            cfg.discord_webhook, json.dumps({"content": f"**{title}**\n{body}"}).encode(),
            {"Content-Type": "application/json"})))
    if cfg.telegram_bot_token and cfg.telegram_chat_id:
        targets.append(("telegram", lambda: _post(
            f"https://api.telegram.org/bot{cfg.telegram_bot_token}/sendMessage",
            json.dumps({"chat_id": cfg.telegram_chat_id, "text": f"{title}\n{body}"}).encode(),
            {"Content-Type": "application/json"})))
    for name, fn in targets:
        try:
            fn()
        except Exception as e:
            print(f"[warn] {name} alert failed: {e}")
