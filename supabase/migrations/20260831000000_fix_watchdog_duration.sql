-- Fix: the watchdog understated long outages, badly.
--
-- 20260828140000 formatted the outage with to_char(silent_for, 'HH24:MI'),
-- which silently drops the days field of an interval. Found the first time it
-- ran against real data: a worker that had been down for 60 days reported
--
--     "No heartbeat for 07:12"
--
-- and a clean 24-hour outage would have reported "00:00" — zero. The alert
-- exists to convey how bad it is; an alert that says seven hours when it means
-- two months is worse than no number at all, because it reads as recent.
--
-- The replacement scales the unit to the magnitude:
--     45 minutes    → "45 minutes"
--     7h 12m        → "7h 12m"
--     60d 07:12     → "60d 7h"

CREATE OR REPLACE FUNCTION public.format_outage(silent_for INTERVAL)
RETURNS TEXT
LANGUAGE sql
IMMUTABLE
SET search_path = ''
AS $$
    SELECT CASE
        WHEN silent_for >= INTERVAL '1 day' THEN
             (EXTRACT(EPOCH FROM silent_for)::bigint / 86400)::text || 'd '
          || ((EXTRACT(EPOCH FROM silent_for)::bigint % 86400) / 3600)::text || 'h'
        WHEN silent_for >= INTERVAL '1 hour' THEN
             (EXTRACT(EPOCH FROM silent_for)::bigint / 3600)::text || 'h '
          || ((EXTRACT(EPOCH FROM silent_for)::bigint % 3600) / 60)::text || 'm'
        ELSE (EXTRACT(EPOCH FROM silent_for)::bigint / 60)::text || ' minutes'
    END;
$$;

CREATE OR REPLACE FUNCTION public.check_worker_heartbeat()
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
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
                       || public.format_outage(silent_for)
                       || '. Chat and approvals will not be answered until the '
                       || 'worker is running again.',
            'tags',     jsonb_build_array('warning'),
            'priority', 4
        )
    );

    UPDATE public.watchdog_config SET last_alerted_at = NOW() WHERE id = 1;
END;
$$;

REVOKE ALL ON FUNCTION public.check_worker_heartbeat() FROM PUBLIC;

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
