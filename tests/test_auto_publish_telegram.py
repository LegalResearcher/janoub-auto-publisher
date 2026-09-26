import os
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime, timezone
from unittest.mock import patch

_TEST_TMP = tempfile.TemporaryDirectory(prefix="janoub-telegram-test-")
_ORIGINAL_CWD = os.getcwd()
os.environ["BOT_DATA_DIR"] = os.path.join(_TEST_TMP.name, "data")
os.environ["SUPABASE_URL"] = "https://example.invalid"
os.environ["SUPABASE_SERVICE_KEY"] = "unit-test-service-key"
os.chdir(_TEST_TMP.name)
try:
    import janoub_news_bot as janoub
    import auto_publish_janoub as publisher
finally:
    os.chdir(_ORIGINAL_CWD)


class AutoPublishTelegramTests(unittest.TestCase):
    def _item(self, video_url="https://youtu.be/video123", photo_file_id=None):
        return {
            "title": "عنوان خبر تجريبي",
            "link": "https://t.me/c/1234567890/27",
            "pub_date": datetime(2026, 9, 25, tzinfo=timezone.utc),
            "raw_body": "عنوان خبر تجريبي\n\nالنص الخام الكامل من المنشور.",
            "source_feed": "telegram://-1001234567890",
            "image_url": None,
            "category": "أخبار وتقارير",
            "author": None,
            "_telegram_source": True,
            "_telegram_update_id": 91,
            "_telegram_photo_file_id": photo_file_id,
            "_telegram_video_url": video_url,
        }

    def _patch_run_dependencies(self, stack, item):
        mocked = {}

        def p(name, **kwargs):
            mocked[name] = stack.enter_context(patch.object(publisher, name, **kwargs))
            return mocked[name]

        p("check_system_logs_size")
        p("check_and_notify_scheduled_posts")
        p("get_existing_source_urls", return_value=set())
        p("load_blocked_links", return_value=set())
        p("get_recent_published_titles", return_value=[])
        p("collect_recent_items", return_value=[])
        p("is_telegram_source_configured", return_value=True)
        p("fetch_telegram_items", return_value=([item], 91))
        p("remove_duplicate_news", side_effect=lambda items, history_items, duplicates_out=None: items)
        p("apply_full_extraction")
        p("rewrite_article", return_value={
            "title": "عنوان محرر",
            "excerpt": "ملخص محرر",
            "content": "متن محرر كامل.",
        })
        p("check_similar_published_title_db", return_value=None)
        p("word_stats", return_value=(4, 1))
        p("format_content_paragraphs", return_value="<p>متن محرر كامل.</p>")
        p("download_telegram_photo", return_value=b"telegram-photo-bytes")
        p("get_post_image_url", return_value=(None, None))
        p("make_slug", return_value="news-slug")
        p("generate_meta_title", return_value="SEO title")
        p("generate_meta_description", return_value="SEO description")
        p("sb_insert", return_value="post-id")
        p("get_published_post_by_title", return_value={
            "id": "existing-post-id",
            "title": "عنوان الخبر الأصلي",
            "external_video_url": None,
        })
        p("update_published_post_video_url", return_value=True)
        p("update_published_post_cover_image", return_value=True)
        p("log_published_title")
        p("save_blocked_link")
        p("seed_views")
        p("build_canonical_url", return_value="https://janoub.example/news-slug")
        p("send_to_telegram", return_value=True)
        p("log_discovery_ready")
        p("commit_telegram_cursor")
        return mocked

    def test_telegram_video_url_is_saved_in_external_video_field(self):
        with ExitStack() as stack:
            mocked = self._patch_run_dependencies(stack, self._item())
            publisher.run()

        record = mocked["sb_insert"].call_args.args[0]
        self.assertEqual(record["external_video_url"], "https://youtu.be/video123")
        self.assertNotIn("https://youtu.be/video123", record["title"])
        self.assertNotIn("https://youtu.be/video123", record["excerpt"])
        self.assertNotIn("https://youtu.be/video123", record["content"])

    def test_no_video_url_is_saved_as_null(self):
        with ExitStack() as stack:
            mocked = self._patch_run_dependencies(stack, self._item(video_url=None))
            publisher.run()

        record = mocked["sb_insert"].call_args.args[0]
        self.assertIsNone(record["external_video_url"])

    def test_photo_attached_to_original_telegram_post_is_downloaded_and_processed(self):
        item = self._item(video_url="https://x.com/source/status/12345", photo_file_id="original-post-photo")
        with ExitStack() as stack:
            mocked = self._patch_run_dependencies(stack, item)
            mocked["get_post_image_url"].return_value = ("https://cdn.example/photo.webp", None)
            publisher.run()

        mocked["download_telegram_photo"].assert_called_once_with("original-post-photo")
        mocked["get_post_image_url"].assert_called_once_with(
            None,
            headline_text="عنوان محرر",
            article_url=item["link"],
            source_image_bytes=b"telegram-photo-bytes",
        )
        record = mocked["sb_insert"].call_args.args[0]
        self.assertEqual(record["image_url"], "https://cdn.example/photo.webp")
        self.assertEqual(record["external_video_url"], "https://x.com/source/status/12345")

    def test_duplicate_telegram_video_updates_existing_article_instead_of_being_dropped(self):
        item = self._item(video_url="https://x.com/aljanoubvoice2/status/2103854341472059432")

        def mark_as_duplicate(items, history_items, duplicates_out=None):
            if duplicates_out is not None:
                for duplicate in items:
                    duplicate["_duplicate_match_title"] = "عنوان الخبر الأصلي"
                    duplicates_out.append(duplicate)
            return []

        with ExitStack() as stack:
            mocked = self._patch_run_dependencies(stack, item)
            mocked["remove_duplicate_news"].side_effect = mark_as_duplicate
            publisher.run()

        mocked["get_published_post_by_title"].assert_called_once_with("عنوان الخبر الأصلي")
        mocked["update_published_post_video_url"].assert_called_once_with(
            "existing-post-id", "https://x.com/aljanoubvoice2/status/2103854341472059432"
        )
        mocked["sb_insert"].assert_not_called()
        mocked["commit_telegram_cursor"].assert_called_once_with(91)

    def test_remove_duplicate_news_returns_historical_media_match_for_update(self):
        now = datetime.now(timezone.utc)
        item = self._item(video_url="https://x.com/source/status/123")
        item["pub_date"] = now
        duplicates = []
        with (
            patch.object(janoub, "get_title_embedding", return_value=[1.0, 0.0]),
            patch.object(janoub, "_cosine_similarity", return_value=0.99),
        ):
            kept = janoub.remove_duplicate_news(
                [item],
                history_items=[{
                    "title": "عنوان الخبر السابق",
                    "pub_date": now,
                    "embedding": [1.0, 0.0],
                }],
                duplicates_out=duplicates,
            )

        self.assertEqual(kept, [])
        self.assertEqual(duplicates, [item])
        self.assertEqual(item["_duplicate_match_title"], "عنوان الخبر السابق")

    def test_duplicate_telegram_video_merges_into_kept_story_from_same_batch(self):
        now = datetime.now(timezone.utc)
        primary = self._item(video_url=None)
        primary.update({"title": "عنوان الخبر الأساسي", "pub_date": now})
        duplicate = self._item(video_url="https://x.com/source/status/123")
        duplicate.update({"title": "عنوان صياغته مختلفة", "pub_date": now})
        with (
            patch.object(janoub, "get_title_embedding", return_value=[1.0, 0.0]),
            patch.object(janoub, "_cosine_similarity", return_value=0.99),
        ):
            kept = janoub.remove_duplicate_news([primary, duplicate], history_items=[])

        self.assertEqual(kept, [primary])
        self.assertEqual(primary["_telegram_video_url"], "https://x.com/source/status/123")


if __name__ == "__main__":
    unittest.main()
