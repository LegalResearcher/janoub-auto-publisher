import os
import tempfile
import unittest
from unittest.mock import patch

# janoub_news_bot requires Supabase credentials at import time and initializes
# log/data paths. Use inert test-only values and a temporary working directory.
_TEST_TMP = tempfile.TemporaryDirectory(prefix="janoub-image-test-")
_ORIGINAL_CWD = os.getcwd()
os.environ["BOT_DATA_DIR"] = os.path.join(_TEST_TMP.name, "data")
os.environ["SUPABASE_URL"] = "https://example.invalid"
os.environ["SUPABASE_SERVICE_KEY"] = "unit-test-service-key"
os.chdir(_TEST_TMP.name)
try:
    from janoub_news_bot import get_post_image_url
    import janoub_news_bot as janoub
finally:
    os.chdir(_ORIGINAL_CWD)


class TelegramImagePipelineTests(unittest.TestCase):
    def test_source_bytes_use_existing_processing_and_storage_pipeline(self):
        raw = b"fake-telegram-photo-bytes"
        with (
            patch.object(janoub, "HEADLINE_DESIGN_ENABLED", False),
            patch.object(janoub, "GENERATE_SQUARE_IMAGE_VARIANT", False),
            patch.object(janoub, "image_contains_blocked_logo", return_value=False),
            patch.object(janoub, "compress_image_to_webp", return_value=b"processed-webp" ) as compress,
            patch.object(janoub, "upload_image_to_supabase", return_value="https://cdn.example/photo.webp") as upload,
            patch.object(janoub, "download_image_bytes") as download_url,
            patch.object(janoub, "fetch_og_image") as fetch_og,
        ):
            image_url, square_url = get_post_image_url(
                None,
                article_url="https://t.me/c/4430613399/12",
                headline_text="عنوان الخبر",
                source_image_bytes=raw,
            )
        self.assertEqual(image_url, "https://cdn.example/photo.webp")
        self.assertIsNone(square_url)
        compress.assert_called_once_with(raw)
        upload.assert_called_once()
        download_url.assert_not_called()
        fetch_og.assert_not_called()


if __name__ == "__main__":
    unittest.main()
