import fcntl
import os
import sys

# ══════════════════════════════════════════════════════════════════════
#  🔒 نفس آلية القفل المستخدمة بسكربت حصاد اليوم (auto_publish_alittihad_
#  alkhabar.py) — تمنع تشغيلين متزامنين لهذا السكربت لو تشغيل سابق عبر
#  cron لسه شغّال ولم ينتهِ قبل بداية التشغيل التالي.
# ══════════════════════════════════════════════════════════════════════
# ملاحظة: على GitHub Actions لا حاجة فعلية لهذا القفل — كل تشغيلة على
# runner منفصل تماماً أصلاً. أبقيناه فقط لبقاء نفس السلوك لو شغّلت
# السكربت يدوياً من مكان آخر بالتوازي.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.environ.get("BOT_DATA_DIR", os.path.join(_SCRIPT_DIR, "janoub_data"))
LOCK_FILE_PATH = os.path.join(_DATA_DIR, "auto_publish_janoub.lock")

sys.path.insert(0, _SCRIPT_DIR)

from janoub_news_bot import (
    log,
    RSS_MASA_URL,
    RSS_MASA_CATEGORY,
    RSS_ADEN_TM_FULL_URL,
    RSS_ADEN_TM_FULL_CATEGORY,
    RSS_ADEN_ALGHAD_SPORT_URL,
    RSS_ADEN_ALGHAD_SPORT_CATEGORY,
    RSS_YPAGENCY_OCCUPIED_PROVINCES_URL,
    RSS_YPAGENCY_OCCUPIED_PROVINCES_CATEGORY,
    RSS_ALNAQABI_FULL_URL,
    RSS_ALNAQABI_FULL_CATEGORY,
    NO_REWRITE_CATEGORIES,
    NO_IMAGE_CATEGORIES,
    FEATURED_SLIDER_CATEGORIES,
    DEFAULT_OPINION_AUTHOR,
    SOURCE_LABEL,
    check_system_logs_size,
    check_and_notify_scheduled_posts,
    get_existing_source_urls,
    get_published_post_by_source_url,
    get_published_post_by_title,
    get_recent_published_titles,
    log_published_title,
    check_similar_published_title_db,
    load_blocked_links,
    save_blocked_link,
    collect_recent_items,
    remove_duplicate_news,
    apply_full_extraction,
    rewrite_article,
    rewrite_title_only,
    get_post_image_url,
    word_stats,
    format_content_paragraphs,
    make_slug,
    get_or_create_author_id,
    generate_meta_title,
    generate_meta_description,
    sb_insert,
    seed_views,
    build_canonical_url,
    send_to_telegram,
    log_discovery_ready,
    update_published_post_cover_image,
    update_published_post_video_url,
)
from telegram_source import (
    TelegramFileTooLargeError,
    commit_telegram_cursor,
    download_telegram_photo,
    fetch_telegram_items,
    is_configured as is_telegram_source_configured,
    merge_photo_replies_with_news_items,
)

# ══════════════════════════════════════════════════════════════════════
#  🔒 نسخة تلقائية — تعمل فقط على المصدرين اللذين لا يحتاجان تحديث ملفات
#  XML يدوياً (فيد عدن تايم الحي الكامل + فيد المساء برس)، بنفس منطق وضع
#  "1" (استخراج الخبر كاملاً) + الوضع التلقائي (كل خبر بقسمه الخاص) من
#  janoub_news_bot.py الأصلي، لكن بدون أي تفاعل يدوي (بدون أسئلة استخراج/
#  تصنيف/استثناء/جدولة، وبدون طلب كتابة "تأكيد") — تُنشر كل الأخبار فوراً
#  (status=published). تُشغَّل عبر cron كل عدة دقائق.
# ══════════════════════════════════════════════════════════════════════

SELECTED_FEEDS = {
    RSS_ADEN_TM_FULL_URL: RSS_ADEN_TM_FULL_CATEGORY,
    RSS_ALNAQABI_FULL_URL: RSS_ALNAQABI_FULL_CATEGORY,
    # ⏸️ فيد الرياضة متوقف مؤقتاً — أزل التعليق عن السطر لإعادة تفعيله:
    # RSS_ADEN_ALGHAD_SPORT_URL: RSS_ADEN_ALGHAD_SPORT_CATEGORY,
    RSS_YPAGENCY_OCCUPIED_PROVINCES_URL: RSS_YPAGENCY_OCCUPIED_PROVINCES_CATEGORY,
    # ⏸️ المساء برس متوقف مؤقتًا — أزل التعليق عن السطر لإعادة تفعيله:
    # RSS_MASA_URL: RSS_MASA_CATEGORY,
}

# 🚫 أقسام مستبعدة كلياً من النشر التلقائي (تبقى متاحة بالوضع التفاعلي
# اليدوي بـjanoub_news_bot.py كما هي، هذا الاستبعاد خاص بالسكربت التلقائي فقط)
EXCLUDED_AUTO_CATEGORIES = {
    "آراء واتجاهات",
    "أسعار العملات والذهب",
    "رياضة",
}

# 🚫 كلمات مفتاحية تستبعد الخبر تلقائياً لو ظهرت بعنوانه أو نصه، بمعزل عن
# قسمه (نشرات متكررة قصيرة العمر لا تناسب أرشيف الموقع: عاجل/طقس/كهرباء/
# أذان/ذهب/صرف). خاص بالسكربت التلقائي فقط، مثل EXCLUDED_AUTO_CATEGORIES.
BLOCKED_AUTO_TOPIC_KEYWORDS = [
    "عاجل",
    "الطقس",
    "الكهرباء",
    "اذان",
    "أذان",
    "الذهب",
    "الصرف",
]

# وصف RSS في النقابي الجنوبي يضيف هذه الترويسة الثابتة قبل متن كل خبر.
# تحتوي الترويسة كلمة «العاجلة»، فلا ينبغي أن تجعل كل أخبار المصدر محظورة.
NAQABI_RSS_BOILERPLATE = (
    "النقابي الجنوبي: | alnaqbi aljanubi نرصد أخر أخبار الحدث الجنوبي العاجلة"
)
NAQABI_RSS_BOILERPLATE_ALT = (
    "النقابي الجنوبي: | alnaqbi aljanubi نرصد آخر أخبار الحدث الجنوبي العاجلة"
)


def _is_blocked_auto_topic(it: dict) -> bool:
    text = f"{it.get('title', '')} {it.get('raw_body', '')}"
    if it.get("source_feed") == RSS_ALNAQABI_FULL_URL:
        # تجاهل ترويسة المصدر، مع السماح بكلمة «عاجل» في عنوان/متن الخبر
        # الحقيقي، كما في التشغيل التلقائي لشمسان نيوز.
        text = text.replace(NAQABI_RSS_BOILERPLATE, "")
        text = text.replace(NAQABI_RSS_BOILERPLATE_ALT, "")
        keywords = [kw for kw in BLOCKED_AUTO_TOPIC_KEYWORDS if kw != "عاجل"]
    else:
        keywords = BLOCKED_AUTO_TOPIC_KEYWORDS
    return any(kw in text for kw in keywords)


def _log_source_counts(label: str, items: list[dict]) -> None:
    """يسجل عدد العناصر لكل فيد حتى يظهر موضع استبعاد أخبار أي مصدر بوضوح."""
    counts: dict[str, int] = {}
    for it in items:
        source = it.get("source_feed") or "(مصدر غير معروف)"
        counts[source] = counts.get(source, 0) + 1
    details = " | ".join(f"{source}: {count}" for source, count in counts.items()) or "لا شيء"
    log.info(f"📊 {label} حسب المصدر: {details}")


def _process_late_telegram_photo_replies(photo_replies: list[dict]) -> bool:
    """إرفاق صور/روابط فيديو الردود بالمقالات المنشورة دون إعادة نشرها.

    يرجع True عند فشل مؤقت يستوجب إبقاء مؤشر Telegram لإعادة المحاولة.
    """
    retry_required = False
    for reply in photo_replies:
        source_url = reply.get("link")
        try:
            published_post = get_published_post_by_source_url(source_url)
        except Exception as error:
            log.error(
                "❌ تعذّر العثور على خبر Telegram لربط مرفق الرد (%s)؛ ستعاد المحاولة.",
                type(error).__name__,
            )
            retry_required = True
            continue

        if not published_post:
            log.info(
                "ℹ️ مرفق رد Telegram للمنشور %s ينتظر نشر الخبر الأصلي؛ ستعاد المحاولة.",
                reply.get("_telegram_reply_to_message_id"),
            )
            retry_required = True
            continue

        video_url = reply.get("_telegram_video_url")
        if video_url:
            try:
                if not update_published_post_video_url(published_post["id"], video_url):
                    retry_required = True
                    continue
                log.info(
                    "✅ حُدّث رابط فيديو الخبر المنشور «%s».",
                    published_post.get("title", "")[:70],
                )
            except Exception as error:
                log.error(
                    "❌ تعذّر تحديث رابط فيديو Telegram؛ ستعاد المحاولة (%s).",
                    type(error).__name__,
                )
                retry_required = True
                continue

        if not reply.get("_telegram_photo_file_id"):
            continue

        try:
            source_image = download_telegram_photo(reply["_telegram_photo_file_id"])
        except TelegramFileTooLargeError as error:
            log.warning("⚠️ صورة رد Telegram أكبر من حد التنزيل؛ لن تُرفق: %s", error)
            continue
        except Exception as error:
            log.error(
                "❌ تعذّر تنزيل صورة رد Telegram؛ ستعاد المحاولة (%s).",
                type(error).__name__,
            )
            retry_required = True
            continue

        try:
            image_url, _ = get_post_image_url(
                None,
                headline_text=published_post.get("title"),
                source_image_bytes=source_image,
            )
        except Exception as error:
            log.error(
                "❌ تعذّرت معالجة صورة رد Telegram؛ ستعاد المحاولة (%s).",
                type(error).__name__,
            )
            retry_required = True
            continue
        if not image_url:
            log.warning("⚠️ لم تنتج معالجة صورة رد Telegram غلافًا؛ سيبقى الخبر بلا تغيير.")
            continue

        try:
            updated = update_published_post_cover_image(published_post["id"], image_url)
        except Exception as error:
            log.error(
                "❌ تعذّر تحديث صورة الخبر المنشور من رد Telegram؛ ستعاد المحاولة (%s).",
                type(error).__name__,
            )
            retry_required = True
            continue
        if not updated:
            log.error("❌ لم يُؤكَّد تحديث غلاف خبر Telegram؛ ستعاد المحاولة.")
            retry_required = True
            continue
        log.info(
            "✅ أُلحقت صورة رد Telegram بالخبر المنشور «%s».",
            published_post.get("title", "")[:70],
        )
    return retry_required


def _process_duplicate_telegram_media(duplicate_items: list[dict]) -> bool:
    """Attach media from a deduplicated Telegram repost to its published match."""
    retry_required = False
    for item in duplicate_items:
        match_title = item.get("_duplicate_match_title")
        if not match_title:
            continue
        try:
            published_post = get_published_post_by_title(match_title)
        except Exception as error:
            log.error(
                "❌ تعذّر العثور على الخبر المنشور المطابق لإرفاق وسائط Telegram؛ ستعاد المحاولة (%s).",
                type(error).__name__,
            )
            retry_required = True
            continue
        if not published_post:
            log.warning(
                "⚠️ لم يُعثر على سجل منشور مطابق لعنوان التكرار «%s»؛ لم يُنشر خبر مكرر.",
                match_title[:70],
            )
            continue

        video_url = item.get("_telegram_video_url")
        if video_url and published_post.get("external_video_url") != video_url:
            try:
                if not update_published_post_video_url(published_post["id"], video_url):
                    retry_required = True
                    continue
                log.info(
                    "✅ أُرفق رابط فيديو Telegram بخبر مكرر مطابق «%s».",
                    published_post.get("title", match_title)[:70],
                )
            except Exception as error:
                log.error(
                    "❌ تعذّر تحديث فيديو المقال المطابق؛ ستعاد المحاولة (%s).",
                    type(error).__name__,
                )
                retry_required = True
                continue

        photo_file_id = item.get("_telegram_photo_file_id")
        if not photo_file_id:
            continue
        try:
            source_image = download_telegram_photo(photo_file_id)
            image_url, _ = get_post_image_url(
                None,
                headline_text=published_post.get("title") or match_title,
                source_image_bytes=source_image,
            )
        except TelegramFileTooLargeError as error:
            log.warning("⚠️ صورة Telegram للخبر المكرر أكبر من حد التنزيل؛ لن تُرفق: %s", error)
            continue
        except Exception as error:
            log.error(
                "❌ تعذّر تنزيل/معالجة صورة الخبر المكرر؛ ستعاد المحاولة (%s).",
                type(error).__name__,
            )
            retry_required = True
            continue
        if not image_url:
            log.warning("⚠️ لم تنتج معالجة صورة Telegram للخبر المكرر غلافًا.")
            continue
        try:
            if not update_published_post_cover_image(published_post["id"], image_url):
                retry_required = True
                continue
            log.info(
                "✅ أُرفقت صورة Telegram بخبر مكرر مطابق «%s»." ,
                published_post.get("title", match_title)[:70],
            )
        except Exception as error:
            log.error(
                "❌ تعذّر تحديث صورة المقال المطابق؛ ستعاد المحاولة (%s).",
                type(error).__name__,
            )
            retry_required = True
    return retry_required


def run():
    log.info("═" * 60)
    log.info("  📰  الجنوب فويس — تشغيل تلقائي (عدن تايم + المساء برس)")
    log.info("═" * 60)

    check_system_logs_size()
    check_and_notify_scheduled_posts()

    existing_urls = get_existing_source_urls()
    blocked_links = load_blocked_links()
    recent_published = get_recent_published_titles(hours=24)

    items = collect_recent_items(SELECTED_FEEDS)
    telegram_cursor = None
    telegram_retry_required = False
    try:
        if is_telegram_source_configured():
            telegram_items, telegram_cursor = fetch_telegram_items()
            telegram_items, photo_replies = merge_photo_replies_with_news_items(
                telegram_items,
                existing_source_urls=existing_urls | blocked_links,
            )
            if photo_replies:
                telegram_retry_required = _process_late_telegram_photo_replies(photo_replies)
            items.extend(telegram_items)
            log.info(f"📨 منشورات تيليجرام الجديدة: {len(telegram_items)}")
    except Exception as e:
        # A Telegram source outage or partial setup must not stop the RSS feeds.
        log.error(f"تعذّر جلب منشورات مصدر تيليجرام؛ ستستمر فيدات RSS: {e}")
    _log_source_counts("بعد سحب RSS وقبل فحص الرابط", items)
    new_items = [
        it for it in items
        if it["link"] not in existing_urls and it["link"] not in blocked_links
    ]
    _log_source_counts("بعد استبعاد الروابط المنشورة/المحظورة", new_items)
    duplicate_media_items: list[dict] = []
    new_items = remove_duplicate_news(
        new_items,
        history_items=recent_published,
        duplicates_out=duplicate_media_items,
    )
    if duplicate_media_items:
        telegram_retry_required = (
            _process_duplicate_telegram_media(duplicate_media_items)
            or telegram_retry_required
        )
    _log_source_counts("بعد استبعاد الأخبار المتشابهة", new_items)

    blocked_topic_count = sum(1 for it in new_items if _is_blocked_auto_topic(it))
    if blocked_topic_count:
        new_items = [it for it in new_items if not _is_blocked_auto_topic(it)]
        log.info(f"🚫 استُبعد {blocked_topic_count} خبر (يحتوي كلمة ممنوعة: عاجل/طقس/كهرباء/أذان/ذهب/صرف).")
    _log_source_counts("بعد فلتر الكلمات المحظورة التلقائي", new_items)

    log.info("─" * 60)
    log.info(f"✅ إجمالي الأخبار الجديدة المؤهلة للنشر: {len(new_items)}")
    log.info("─" * 60)

    if not new_items:
        log.info("لا يوجد أخبار جديدة حالياً.")
        if telegram_cursor is not None and not telegram_retry_required:
            commit_telegram_cursor(telegram_cursor)
        return

    rss_items = [it for it in new_items if not it.get("_telegram_source")]
    if rss_items:
        log.info(f"🧲 استخراج النص الكامل لأخبار RSS من صفحاتها ({len(rss_items)} خبر)...")
        apply_full_extraction(rss_items)
    excluded_count = sum(1 for it in new_items if it.get("_excluded"))
    if excluded_count:
        new_items = [it for it in new_items if not it.get("_excluded")]
        log.info(f"🚫 استُبعد {excluded_count} خبر (قسم غير معروف/تعذّر اكتشافه من صفحته).")
    _log_source_counts("بعد استخراج النص الكامل واستبعاد الأقسام غير المعروفة", new_items)

    if not new_items:
        log.info("لا يوجد أخبار جديدة حالياً بعد الاستبعاد.")
        if telegram_cursor is not None and not telegram_retry_required:
            commit_telegram_cursor(telegram_cursor)
        return

    # فلتر الأقسام المستبعدة كلياً من النشر التلقائي — بعد الاستخراج الكامل
    # مباشرة، لأن قسم أخبار عدن تايم يُصحَّح تلقائياً بهذه المرحلة تحديداً
    category_excluded_count = sum(1 for it in new_items if it["category"] in EXCLUDED_AUTO_CATEGORIES)
    if category_excluded_count:
        new_items = [it for it in new_items if it["category"] not in EXCLUDED_AUTO_CATEGORIES]
        log.info(
            f"🚫 استُبعد {category_excluded_count} خبر (قسم مستبعد من النشر التلقائي: "
            "آراء واتجاهات/أسعار العملات والذهب)."
        )
    _log_source_counts("بعد استبعاد الأقسام غير المسموحة", new_items)

    if not new_items:
        log.info("لا يوجد أخبار جديدة حالياً بعد الاستبعاد.")
        if telegram_cursor is not None and not telegram_retry_required:
            commit_telegram_cursor(telegram_cursor)
        return

    ok = fail = skipped = duplicate_count = 0

    for it in new_items:
        post_category = it["category"]
        is_opinion = post_category in NO_REWRITE_CATEGORIES

        if is_opinion:
            log.info(f"📝 إعادة صياغة العنوان فقط (مقال رأي منسوب — النص الأصلي بلا تعديل): {it['title'][:60]}")
            raw_body = it["raw_body"].strip()
            new_title = rewrite_title_only(it["title"], raw_body)
            final_title = new_title or it["title"].strip()
            final_excerpt = (raw_body[:200].rstrip() + "…") if len(raw_body) > 200 else raw_body
            final_content = raw_body
        else:
            log.info(f"✍️  إعادة صياغة: {it['title'][:60]}")
            try:
                rewritten = rewrite_article(
                    it["title"],
                    it["raw_body"],
                    post_category,
                    bypass_houthi_iran_filter=bool(it.get("_telegram_source")),
                    bypass_content_filters=bool(it.get("_telegram_source")),
                    video_url=it.get("_telegram_video_url") if it.get("_telegram_source") else None,
                )
            except Exception as e:
                log.error(f"  ❌ فشلت إعادة الصياغة: {e}")
                if it.get("_telegram_source"):
                    telegram_retry_required = True
                fail += 1
                continue

            if not rewritten:
                if it.get("_telegram_source"):
                    telegram_retry_required = True
                skipped += 1
                continue

            final_title = rewritten["title"].strip()
            final_excerpt = rewritten["excerpt"].strip()
            final_content = rewritten["content"]

        # 🔁 فحص تكرار عبر قاعدة البيانات مباشرة (check_similar_published_title):
        # نفس الفحص المضاف بـjanoub_news_bot.py — يسأل Supabase هل نُشر خبر
        # مشابه لهذا العنوان خلال آخر 48 ساعة، بمعزل تام عن السجل المحلي
        # (recent_published/remove_duplicate_news بالأعلى يفحصان فقط داخل هذا
        # الجهاز)، فيمسك التكرار حتى لو شُغّل البوت من جهاز آخر أو انحذف/تأخر
        # تحديث السجل المحلي.
        dup_match = check_similar_published_title_db(final_title)
        if dup_match:
            if it.get("_telegram_video_url") or it.get("_telegram_photo_file_id"):
                it["_duplicate_match_title"] = dup_match["title"]
                if _process_duplicate_telegram_media([it]):
                    telegram_retry_required = True
            log.info(
                f"  🔁 تخطي — يشابه خبراً منشوراً سابقاً (تشابه "
                f"{dup_match['similarity_score']:.0%}): «{dup_match['title'][:60]}»"
            )
            duplicate_count += 1
            continue

        words, reading_time = word_stats(final_content)
        formatted_content = format_content_paragraphs(final_content)
        item_date = it["pub_date"].isoformat()
        telegram_image_bytes = None
        if it.get("_telegram_photo_file_id"):
            try:
                telegram_image_bytes = download_telegram_photo(it["_telegram_photo_file_id"])
            except TelegramFileTooLargeError as e:
                log.warning(f"  ⚠️  {e} سيُنشر الخبر النصي دون صورة.")
            except Exception as e:
                log.error(f"  ❌ تعذّر تنزيل صورة منشور تيليجرام؛ سيُعاد الخبر في التشغيل التالي: {e}")
                fail += 1
                continue

        if post_category in NO_IMAGE_CATEGORIES:
            log.info(f"  🚫 قسم «{post_category}»: يُنشر بدون صورة دائماً — تم تجاوز جلب/رفع الصورة.")
            image_url = None
            image_url_square = None
        elif it.get("_telegram_source") and telegram_image_bytes is None:
            # Text-only Telegram posts have no article page to scrape for og:image.
            image_url = None
            image_url_square = None
        else:
            # 🖼️ صورة الخبر الأصلية من المصدر (RSS) — استُخرجت مسبقاً وقت
            # جلب الفيد عبر extract_image_url() وخُزّنت بـit["image_url"].
            # لو فارغة: get_post_image_url تجرب og:image من صفحة الخبر (it["link"])
            # كخط احتياطي قبل الاستسلام.
            image_url, image_url_square = get_post_image_url(
                it.get("image_url"),
                headline_text=final_title,
                article_url=it.get("link"),
                source_image_bytes=telegram_image_bytes,
            )

        record = {
            "title": final_title,
            "slug": make_slug(final_title),
            "excerpt": final_excerpt,
            "content": formatted_content,
            "category": post_category,
            "source": SOURCE_LABEL,
            "source_url": it["link"],
            "status": "published",
            "word_count": words,
            "reading_time": reading_time,
            "created_at": item_date,
            "published_at": item_date,
            "updated_at": item_date,
            "image_url": image_url,
            "thumbnail_image": image_url_square,
            "external_video_url": it.get("_telegram_video_url"),
            "meta_title": generate_meta_title(final_title),
            "meta_description": generate_meta_description(final_excerpt),
            "featured": post_category in FEATURED_SLIDER_CATEGORIES,
        }

        if is_opinion:
            opinion_author_name = it.get("author") or DEFAULT_OPINION_AUTHOR
            record["author"] = opinion_author_name
            author_id = get_or_create_author_id(opinion_author_name)
            if author_id:
                record["author_id"] = author_id
            else:
                log.warning(
                    f"⚠️  تعذّر ربط/إنشاء الكاتب '{opinion_author_name}' بجدول authors — "
                    "سيُنشر المقال لكن دون بطاقة الكاتب بالموقع."
                )

        post_id = sb_insert(record)
        if post_id:
            ok += 1
            log.info(f"  ✅ نُشر: {record['title'][:60]}")
            log_published_title(record["title"], record["created_at"], embedding=it.get("_title_embedding"))
            save_blocked_link(it["link"])  # منع إعادة النشر مستقبلاً حتى لو حُذف الخبر من الموقع
            seed_views(post_id)
            canonical_url = build_canonical_url(record["slug"], record.get("published_at") or record["created_at"])

            if send_to_telegram(record["title"], canonical_url):
                log.info("  📢 أُرسل لتليجرام")

            log_discovery_ready([canonical_url])
        else:
            fail += 1

    # Commit only after every Telegram item has succeeded or been deliberately
    # skipped. A processing/publication failure leaves updates available to retry.
    if telegram_cursor is not None and fail == 0 and not telegram_retry_required:
        commit_telegram_cursor(telegram_cursor)

    log.info("═" * 60)
    log.info(f"📊 نُشر: {ok} / فشل: {fail} / تُخُطّي: {skipped} / مكرر (قاعدة البيانات): {duplicate_count}")
    log.info("═" * 60)


def _acquire_lock_or_exit():
    """يفتح ملف القفل ويحاول مسكه بشكل غير محظر (LOCK_EX | LOCK_NB). لو
    تشغيل آخر ماسكه فعلاً، يطبع تحذيراً ويخرج فوراً بدون معالجة أي خبر.
    القفل يتحرر تلقائياً عند خروج العملية (نجاح أو فشل أو استثناء)."""
    os.makedirs(os.path.dirname(LOCK_FILE_PATH), exist_ok=True)
    lock_file = open(LOCK_FILE_PATH, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log.warning(
            "  🔒 تشغيل سابق لهذا السكربت لسه شغّال (القفل ممسوك) — "
            "تخطي هذا التشغيل بالكامل لمنع معالجة نفس الأخبار مرتين."
        )
        sys.exit(0)
    return lock_file


if __name__ == "__main__":
    _lock_handle = _acquire_lock_or_exit()
    run()
