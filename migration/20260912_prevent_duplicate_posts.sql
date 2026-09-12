-- منع إدخال الخبر نفسه أكثر من مرة عند تزامن تشغيلين من GitHub Actions.
--
-- هذا الترحيل لا يحذف أي بيانات. إذا كانت هناك روابط مكررة حالياً فسيفشل
-- عمداً قبل إنشاء القيد، ويجب تنظيف التكرارات بعد مراجعتها يدوياً.

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM public.posts
    WHERE source_url IS NOT NULL
    GROUP BY source_url
    HAVING COUNT(*) > 1
    LIMIT 1
  ) THEN
    RAISE EXCEPTION
      'Cannot create unique index: duplicate non-null source_url values exist in public.posts. Review and clean them first.';
  END IF;
END $$;

-- الفهرس الكامل مناسب هنا لأن PostgreSQL يسمح تلقائياً بعدة قيم NULL،
-- كما أنه قابل للاستدلال من on_conflict=source_url في PostgREST.
CREATE UNIQUE INDEX IF NOT EXISTS posts_source_url_unique
  ON public.posts (source_url);
