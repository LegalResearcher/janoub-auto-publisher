import os
import unittest
from datetime import timezone
from unittest.mock import patch

import requests

from telegram_source import (
    _post_link,
    _to_news_item,
    fetch_telegram_items,
    is_configured,
)


class FakeResponse:
    ok = True
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload

    def raise_for_status(self):
        return None


class TelegramSourceTests(unittest.TestCase):
    def test_maps_private_channel_post_to_news_item(self):
        update = {
            "update_id": 91,
            "channel_post": {
                "message_id": 27,
                "date": 1_750_000_000,
                "chat": {"id": -1001234567890, "title": "مصدر خاص"},
                "text": "عنوان الخبر\n\nالفقرة الأولى.\nالفقرة الثانية.",
            },
        }
        item = _to_news_item(update, "-1001234567890")
        self.assertIsNotNone(item)
        self.assertEqual(item["title"], "عنوان الخبر")
        self.assertEqual(item["raw_body"], "عنوان الخبر\n\nالفقرة الأولى.\nالفقرة الثانية.")
        self.assertEqual(item["link"], "https://t.me/c/1234567890/27")
        self.assertEqual(item["category"], "أخبار وتقارير")
        self.assertEqual(item["source_feed"], "telegram://-1001234567890")
        self.assertTrue(item["_telegram_source"])
        self.assertEqual(item["_telegram_update_id"], 91)
        self.assertEqual(item["pub_date"].tzinfo, timezone.utc)

    def test_accepts_caption_as_full_raw_body(self):
        update = {
            "update_id": 92,
            "channel_post": {
                "message_id": 28,
                "date": 1_750_000_000,
                "chat": {"id": -1001234567890, "username": "public_source"},
                "caption": "نص الخبر المصاحب للصورة",
            },
        }
        item = _to_news_item(update, "-1001234567890")
        self.assertEqual(item["raw_body"], "نص الخبر المصاحب للصورة")
        self.assertEqual(item["link"], "https://t.me/public_source/28")

    def test_ignores_other_chats_and_non_channel_updates(self):
        wrong_chat = {
            "update_id": 93,
            "channel_post": {
                "message_id": 29,
                "date": 1_750_000_000,
                "chat": {"id": -1009999999999},
                "text": "نص لا يجب أخذه",
            },
        }
        self.assertIsNone(_to_news_item(wrong_chat, "-1001234567890"))
        self.assertIsNone(_to_news_item({"update_id": 94, "message": {}}, "-1001234567890"))

    def test_private_link_without_numeric_channel_prefix(self):
        self.assertEqual(_post_link({"id": -77}, 10), "https://t.me/c/77/10")

    def test_configuration_is_optional_but_must_be_complete(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(is_configured())
        with patch.dict(os.environ, {"TELEGRAM_SOURCE_BOT_TOKEN": "token"}, clear=True):
            with self.assertRaises(RuntimeError):
                is_configured()

    def test_fetch_uses_persisted_cursor_and_filters_other_chats(self):
        channel_update = {
            "update_id": 81,
            "channel_post": {
                "message_id": 5,
                "date": 1_750_000_000,
                "chat": {"id": -1001234567890},
                "text": "خبر من المصدر",
            },
        }
        other_update = {
            "update_id": 82,
            "channel_post": {
                "message_id": 6,
                "date": 1_750_000_000,
                "chat": {"id": -1005555555555},
                "text": "ليس من المصدر",
            },
        }
        env = {
            "TELEGRAM_SOURCE_BOT_TOKEN": "dedicated-test-token",
            "TELEGRAM_SOURCE_CHAT_ID": "-1001234567890",
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_SERVICE_KEY": "service-key",
        }
        with patch.dict(os.environ, env, clear=True), patch(
            "telegram_source.requests.get",
            side_effect=[
                FakeResponse([{"update_id": 80}]),
                FakeResponse({"ok": True, "result": [channel_update, other_update]}),
            ],
        ) as get:
            items, cursor = fetch_telegram_items()
        self.assertEqual(cursor, 82)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "خبر من المصدر")
        self.assertEqual(get.call_args_list[1].kwargs["params"]["offset"], 81)
        self.assertEqual(get.call_args_list[1].kwargs["params"]["allowed_updates"], '["channel_post"]')

    def test_request_error_never_leaks_bot_token(self):
        token = "do-not-leak-this-token"
        env = {
            "TELEGRAM_SOURCE_BOT_TOKEN": token,
            "TELEGRAM_SOURCE_CHAT_ID": "-1001234567890",
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_SERVICE_KEY": "service-key",
        }
        with patch.dict(os.environ, env, clear=True), patch(
            "telegram_source.requests.get",
            side_effect=[
                FakeResponse([]),
                requests.ConnectionError(f"https://api.telegram.org/bot{token}/getUpdates"),
            ],
        ):
            with self.assertRaises(RuntimeError) as context:
                fetch_telegram_items()
        self.assertNotIn(token, str(context.exception))


if __name__ == "__main__":
    unittest.main()
