-- Dead-man's alarm for the worker.
--
-- This has to run OUTSIDE the Mac. A watchdog inside the worker is worthless:
-- the failure it exists to catch is the worker not running, and a process that
-- is not running sends no alerts. Twelve weeks of silence is what that costs.
--
-- So it lives in Supabase, on pg_cron, and reaches the phone through ntfy —
-- the same channel poll_reminders already uses. Zero additional infrastructure
-- and no dependency on the machine being watched.

-- Both extensions are non-relocatable with fixed schemas (cron, net), so no
-- WITH SCHEMA clause here — specifying one is an error, not a preference.
CREATE EXTENSION IF NOT EXISTS pg_cron;
CREATE EXTENSION IF NOT EXISTS pg_net;

-- Watchdog settings live in a table rather than the function body so the ntfy
-- topic is not baked into a migration in git. Seed it once by hand:
--
--   INSERT INTO public.watchdog_config (id, ntfy_topic)
--   VALUES (1, 'your-topic-here')
--   ON CONFLICT (id) DO UPDATE SET ntfy_topic = EXCLUDED.ntfy_topic;
--
-- Until that topic is set the watchdog is inert — it returns without alerting.
CREATE TABLE IF NOT EXISTS public.watchdog_config (
    id               INT PRIMARY KEY DEFAULT 1,
    ntfy_topic       TEXT,
    stale_after      INTERVAL NOT NULL DEFAULT '15 minutes',
    -- Re-alert cadence. Without this a worker that stays down alerts on every
    -- cron tick, which trains you to ignore the alert.
    realert_after    INTERVAL NOT NULL DEFAULT '6 hours',
    last_alerted_at  TIMESTAMPTZ,
    enabled          BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT watchdog_config_singleton CHECK (id = 1)
);

INSERT INTO public.watchdog_config (id) VALUES (1) ON CONFLICT DO NOTHING;

ALTER TABLE public.watchdog_config ENABLE ROW LEVEL SECURITY;

-- No policy is defined deliberately: this row holds a notification topic and is
-- only ever touched by the SECURITY DEFINER function below and by the service
-- role. RLS with no policy denies all client access, which is what we want.

CREATE OR REPLACE FUNCTION public.check_worker_heartbeat()
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
-- Explicit and minimal: net for http_post, public for our own tables.
SET search_path = net, public
AS $$
DECLARE
    cfg          public.watchdog_config%ROWTYPE;
    last_beat    TIMESTAMPTZ;
    silent_for   INTERVAL;
BEGIN
    SELECT * INTO cfg FROM public.watchdog_config WHERE id = 1;

    IF NOT FOUND OR NOT cfg.enabled OR COALESCE(cfg.ntfy_topic, '') = '' THEN
        RETURN;
    END IF;

    SELECT last_seen INTO last_beat FROM public.mac_heartbeat WHERE id = 1;

    IF last_beat IS NULL THEN
        RETURN;
    END IF;

    silent_for := NOW() - last_beat;

    -- Healthy: clear the alert latch so the next outage notifies immediately
    -- rather than waiting out a realert window left over from a previous one.
    IF silent_for < cfg.stale_after THEN
        IF cfg.last_alerted_at IS NOT NULL THEN
            UPDATE public.watchdog_config
               SET last_alerted_at = NULL
             WHERE id = 1;

            -- net.http_post takes a JSONB body, so this uses ntfy's JSON
            -- publishing API (POST to the root with "topic" in the body)
            -- rather than the plain-text POST-to-/topic form.
            PERFORM net.http_post(
                url     := 'https://ntfy.sh',
                headers := '{"Content-Type": "application/json"}'::jsonb,
                body    := jsonb_build_object(
                    'topic',    cfg.ntfy_topic,
                    'title',    'Sunday is back',
                    'message',  'Worker heartbeat resumed.',
                    'tags',     jsonb_build_array('white_check_mark'),
                    'priority', 2
                )
            );
        END IF;
        RETURN;
    END IF;

    -- Stale, but we already said so recently.
    IF cfg.last_alerted_at IS NOT NULL
       AND NOW() - cfg.last_alerted_at < cfg.realert_after THEN
        RETURN;
    END IF;

    PERFORM net.http_post(
        url     := 'https://ntfy.sh',
        headers := '{"Content-Type": "application/json"}'::jsonb,
        body    := jsonb_build_object(
            'topic',   cfg.ntfy_topic,
            'title',   'Sunday worker is down',
            'message', 'No heartbeat for '
                       || to_char(silent_for, 'HH24:MI')
                       || '. Chat and approvals will not be answered until the '
                       || 'worker is running again.',
            'tags',     jsonb_build_array('warning'),
            'priority', 4
        )
    );

    UPDATE public.watchdog_config SET last_alerted_at = NOW() WHERE id = 1;
END;
$$;

-- This function alerts and writes; nothing client-facing should reach it.
REVOKE ALL ON FUNCTION public.check_worker_heartbeat() FROM PUBLIC;

-- anon/authenticated always exist on Supabase, but a migration that half-applies
-- is worse than one that skips a REVOKE, so guard rather than assume.
DO $revoke$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON FUNCTION public.check_worker_heartbeat() FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON FUNCTION public.check_worker_heartbeat() FROM authenticated;
    END IF;
END
$revoke$;

-- Every 5 minutes. With a 15-minute stale threshold an outage is reported
-- within 20 minutes at worst.
SELECT cron.unschedule('worker-heartbeat-watchdog')
 WHERE EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'worker-heartbeat-watchdog');

SELECT cron.schedule(
    'worker-heartbeat-watchdog',
    '*/5 * * * *',
    $$SELECT public.check_worker_heartbeat()$$
);
