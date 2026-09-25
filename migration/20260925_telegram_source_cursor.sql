-- Stores the last Telegram Bot API update processed by the Janoub publisher.
-- This is cursor metadata only; source posts continue to be recorded in posts.
CREATE TABLE IF NOT EXISTS public.bot_source_cursors (
  source_key text PRIMARY KEY,
  update_id bigint NOT NULL DEFAULT 0,
  updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.bot_source_cursors ENABLE ROW LEVEL SECURITY;

-- No anon/authenticated policies are added. The publisher uses the existing
-- server-side SUPABASE_SERVICE_KEY, which must remain a GitHub Actions secret.
