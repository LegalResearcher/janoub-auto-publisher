#!/usr/bin/env python3
"""Print channel ids from pending channel_post updates without exposing secrets."""
from __future__ import annotations

import os
import sys

import requests


def main() -> int:
    token = os.environ.get("TELEGRAM_SOURCE_BOT_TOKEN", "").strip()
    if not token:
        print("Set TELEGRAM_SOURCE_BOT_TOKEN in the environment first.", file=sys.stderr)
        return 2
    try:
        response = requests.get(
            f"https://api.telegram.org/bot{token}/getUpdates",
            params={"limit": 100, "timeout": 0, "allowed_updates": '["channel_post"]'},
            timeout=20,
        )
    except requests.RequestException as error:
        # The request URL contains the bot token; do not print the raw exception.
        print(f"Telegram request failed ({type(error).__name__}).", file=sys.stderr)
        return 1
    if not response.ok:
        print(f"Telegram returned HTTP {response.status_code}.", file=sys.stderr)
        return 1
    payload = response.json()
    if not payload.get("ok"):
        print("Telegram rejected getUpdates: " + str(payload.get("description", "unknown error")), file=sys.stderr)
        return 1

    channels = {}
    for update in payload.get("result", []):
        post = update.get("channel_post")
        if not post:
            continue
        chat = post.get("chat", {})
        if chat.get("id") is not None:
            channels[str(chat["id"])] = chat.get("title") or "(بدون اسم)"
    if not channels:
        print("No channel_post updates found. Add the bot as a channel administrator and publish a new test post.")
        return 0
    for chat_id, title in channels.items():
        print(f"{chat_id}\t{title}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
