"""Read new channel posts from a private Telegram channel for the Janoub pipeline.

This module uses a dedicated bot token and Telegram Bot API getUpdates. It does
not send messages and never stores the bot token in the repository.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import requests

CURSOR_KEY = "alymenet_private_channel"
CURSOR_TABLE = "bot_source_cursors"
REQUEST_TIMEOUT = 30
MAX_TELEGRAM_DOWNLOAD_BYTES = 20 * 1024 * 1024


class TelegramFileTooLargeError(RuntimeError):
    """The hosted Telegram Bot API cannot download this file size."""


def _required_config() -> tuple[str, str, str, str]:
    token = os.environ.get("TELEGRAM_SOURCE_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_SOURCE_CHAT_ID", "").strip()
    supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    service_key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not token or not chat_id:
        raise RuntimeError(
            "Telegram source is not configured: set TELEGRAM_SOURCE_BOT_TOKEN "
            "and TELEGRAM_SOURCE_CHAT_ID."
        )
    if not supabase_url or not service_key:
        raise RuntimeError(
            "Telegram cursor storage requires SUPABASE_URL and SUPABASE_SERVICE_KEY."
        )
    return token, chat_id, supabase_url, service_key


def is_configured() -> bool:
    token = os.environ.get("TELEGRAM_SOURCE_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_SOURCE_CHAT_ID", "").strip()
    if bool(token) != bool(chat_id):
        raise RuntimeError(
            "Set both TELEGRAM_SOURCE_BOT_TOKEN and TELEGRAM_SOURCE_CHAT_ID, or leave both unset."
        )
    return bool(token and chat_id)


def _supabase_headers(service_key: str) -> dict[str, str]:
    return {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
    }


def get_last_update_id(supabase_url: str, service_key: str) -> int:
    response = requests.get(
        f"{supabase_url}/rest/v1/{CURSOR_TABLE}",
        headers=_supabase_headers(service_key),
        params={"select": "update_id", "source_key": f"eq.{CURSOR_KEY}", "limit": "1"},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    rows = response.json()
    return int(rows[0]["update_id"]) if rows else 0


def save_last_update_id(supabase_url: str, service_key: str, update_id: int) -> None:
    response = requests.post(
        f"{supabase_url}/rest/v1/{CURSOR_TABLE}?on_conflict=source_key",
        headers={
            **_supabase_headers(service_key),
            "Prefer": "resolution=merge-duplicates,return=minimal",
        },
        json={
            "source_key": CURSOR_KEY,
            "update_id": int(update_id),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()


def _post_link(chat: dict[str, Any], message_id: int) -> str:
    username = (chat.get("username") or "").strip().lstrip("@")
    if username:
        return f"https://t.me/{username}/{message_id}"
    chat_id = str(chat.get("id", ""))
    # Telegram's private-channel message links use /c/<channel-id>/<message-id>;
    # Bot API chat ids are represented as -100<channel-id>.
    if chat_id.startswith("-100"):
        return f"https://t.me/c/{chat_id[4:]}/{message_id}"
    return f"https://t.me/c/{chat_id.lstrip('-')}/{message_id}"


def _to_news_item(update: dict[str, Any], expected_chat_id: str) -> dict[str, Any] | None:
    post = update.get("channel_post")
    if not isinstance(post, dict):
        return None
    chat = post.get("chat") or {}
    if str(chat.get("id", "")) != expected_chat_id:
        return None

    # Telegram puts the full raw content in text (or caption when there is media).
    raw_text = (post.get("text") or post.get("caption") or "").strip()
    if not raw_text:
        return None

    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    title = lines[0] if lines else raw_text
    photo_sizes = post.get("photo") or []
    largest_photo = max(
        photo_sizes,
        key=lambda photo: (
            int(photo.get("width") or 0) * int(photo.get("height") or 0),
            int(photo.get("file_size") or 0),
        ),
        default=None,
    )
    # Keep the complete source message as the raw body. This matches the
    # full-extraction input contract and preserves all information for rewriting.
    message_id = int(post["message_id"])
    update_id = int(update["update_id"])
    published_at = datetime.fromtimestamp(
        int(post.get("date") or 0), tz=timezone.utc
    )
    return {
        "title": title,
        "link": _post_link(chat, message_id),
        "pub_date": published_at,
        "raw_body": raw_text,
        "source_feed": f"telegram://{expected_chat_id}",
        "image_url": None,
        "category": "أخبار وتقارير",
        "author": None,
        "_telegram_source": True,
        "_telegram_update_id": update_id,
        "_telegram_photo_file_id": (largest_photo or {}).get("file_id"),
    }


def download_telegram_photo(file_id: str) -> bytes:
    """Download a Telegram photo through getFile without exposing the bot token.

    Telegram's hosted Bot API currently limits downloads to 20 MB. Photos above
    this limit are rejected before the article is published so the cursor can
    remain pending and be retried after the source is corrected.
    """
    token, _, _, _ = _required_config()
    try:
        metadata_response = requests.get(
            f"https://api.telegram.org/bot{token}/getFile",
            params={"file_id": file_id},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as error:
        raise RuntimeError(f"Telegram getFile request failed ({type(error).__name__}).") from None
    if not metadata_response.ok:
        raise RuntimeError(f"Telegram getFile returned HTTP {metadata_response.status_code}.")
    metadata = metadata_response.json()
    if not metadata.get("ok"):
        raise RuntimeError("Telegram getFile failed: " + str(metadata.get("description", "unknown error")))
    file_info = metadata.get("result") or {}
    file_path = file_info.get("file_path")
    file_size = int(file_info.get("file_size") or 0)
    if not file_path:
        raise RuntimeError("Telegram getFile response did not include file_path.")
    if file_size > MAX_TELEGRAM_DOWNLOAD_BYTES:
        raise TelegramFileTooLargeError("Telegram photo exceeds the Bot API 20 MB download limit.")
    try:
        file_response = requests.get(
            f"https://api.telegram.org/file/bot{token}/{file_path}",
            timeout=REQUEST_TIMEOUT,
            stream=True,
        )
    except requests.RequestException as error:
        raise RuntimeError(f"Telegram photo download failed ({type(error).__name__}).") from None
    if not file_response.ok:
        raise RuntimeError(f"Telegram photo download returned HTTP {file_response.status_code}.")
    chunks = []
    downloaded = 0
    try:
        for chunk in file_response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            downloaded += len(chunk)
            if downloaded > MAX_TELEGRAM_DOWNLOAD_BYTES:
                raise TelegramFileTooLargeError("Telegram photo exceeds the Bot API 20 MB download limit.")
            chunks.append(chunk)
    except requests.RequestException as error:
        raise RuntimeError(f"Telegram photo download failed ({type(error).__name__}).") from None
    return b"".join(chunks)


def fetch_telegram_items() -> tuple[list[dict[str, Any]], int | None]:
    """Fetch pending channel posts and the highest update id in the response.

    The caller must save the returned cursor only after the news batch has been
    safely handled. If processing fails, leaving the cursor unchanged causes
    Telegram to return the updates again; the source_url unique index prevents
    already-published posts from being inserted twice.
    """
    if not is_configured():
        return [], None
    token, expected_chat_id, supabase_url, service_key = _required_config()
    last_update_id = get_last_update_id(supabase_url, service_key)
    try:
        response = requests.get(
            f"https://api.telegram.org/bot{token}/getUpdates",
            params={
                "offset": last_update_id + 1,
                "limit": 100,
                "timeout": 0,
                "allowed_updates": '["channel_post"]',
            },
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as error:
        # The Bot API URL contains the token. Never propagate the raw exception.
        raise RuntimeError(f"Telegram getUpdates request failed ({type(error).__name__}).") from None
    if not response.ok:
        raise RuntimeError(f"Telegram getUpdates returned HTTP {response.status_code}.")
    payload = response.json()
    if not payload.get("ok"):
        # Do not include request URLs or credentials in exception text/logs.
        raise RuntimeError(
            "Telegram getUpdates failed: " + str(payload.get("description", "unknown error"))
        )

    updates = payload.get("result") or []
    if not updates:
        return [], None
    highest_update_id = max(int(update["update_id"]) for update in updates)
    items = []
    for update in updates:
        item = _to_news_item(update, expected_chat_id)
        if item:
            items.append(item)
    return items, highest_update_id


def commit_telegram_cursor(update_id: int | None) -> None:
    if update_id is None or not is_configured():
        return
    _, _, supabase_url, service_key = _required_config()
    save_last_update_id(supabase_url, service_key, update_id)
