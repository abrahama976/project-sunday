-- Behavioural tests for check_worker_heartbeat().
-- net.http_post is stubbed to log into a table so we can assert on what would
-- have been sent to ntfy.

CREATE TABLE IF NOT EXISTS public.sent_alerts (
    id serial PRIMARY KEY,
    body jsonb,
    at timestamptz DEFAULT now()
);

CREATE OR REPLACE FUNCTION net.http_post(
    url text,
    body jsonb DEFAULT '{}'::jsonb,
    params jsonb DEFAULT '{}'::jsonb,
    headers jsonb DEFAULT '{}'::jsonb,
    timeout_milliseconds int DEFAULT 5000
) RETURNS bigint
LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO public.sent_alerts (body) VALUES (http_post.body);
    RETURN 1::bigint;
END;
$$;

CREATE OR REPLACE FUNCTION assert(label text, cond boolean) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    IF cond THEN RAISE NOTICE '  ok  %', label;
    ELSE RAISE EXCEPTION 'FAIL: %', label;
    END IF;
END;
$$;

TRUNCATE public.sent_alerts;

-- ── 1. No topic configured → completely inert ─────────────────────────────
UPDATE public.watchdog_config SET ntfy_topic = NULL, last_alerted_at = NULL;
UPDATE public.mac_heartbeat SET last_seen = now() - interval '3 hours';
SELECT public.check_worker_heartbeat();
SELECT assert('unconfigured watchdog stays silent',
              (SELECT count(*) FROM public.sent_alerts) = 0);

-- ── 2. Configured + stale → alerts ────────────────────────────────────────
UPDATE public.watchdog_config SET ntfy_topic = 'test-topic';
SELECT public.check_worker_heartbeat();
SELECT assert('stale heartbeat raises exactly one alert',
              (SELECT count(*) FROM public.sent_alerts) = 1);
SELECT assert('alert is high priority',
              (SELECT body->>'priority' FROM public.sent_alerts ORDER BY id DESC LIMIT 1) = '4');
SELECT assert('alert carries the configured topic',
              (SELECT body->>'topic' FROM public.sent_alerts ORDER BY id DESC LIMIT 1) = 'test-topic');
SELECT assert('alert names the outage duration',
              (SELECT body->>'message' FROM public.sent_alerts ORDER BY id DESC LIMIT 1) LIKE '%3h 0m%');

-- ── Duration formatting ───────────────────────────────────────────────────
-- The original used to_char(interval, 'HH24:MI'), which silently drops the
-- days field. It shipped, and the very first real alert reported a 60-day
-- outage as "07:12". A clean 24-hour outage would have read "00:00" — zero.
-- The old assertion above passed throughout, because it only ever tested a
-- 3-hour outage. These are the cases that would have caught it.
SELECT assert('multi-day outages report days',
              public.format_outage(INTERVAL '60 days 07:12:24') = '60d 7h');
SELECT assert('exactly one day is not reported as zero',
              public.format_outage(INTERVAL '1 day') = '1d 0h');
SELECT assert('sub-hour outages read in minutes',
              public.format_outage(INTERVAL '45 minutes') = '45 minutes');
SELECT assert('hour-scale outages read in hours and minutes',
              public.format_outage(INTERVAL '7 hours 12 minutes') = '7h 12m');
SELECT assert('no outage duration is ever formatted as all-zero',
              public.format_outage(INTERVAL '25 hours') <> '00:00'
              AND public.format_outage(INTERVAL '25 hours') = '1d 1h');
SELECT assert('latch is set', (SELECT last_alerted_at IS NOT NULL FROM public.watchdog_config));

-- ── 3. Still stale, inside realert window → stays quiet ───────────────────
-- This is the rule that stops a long outage alerting every 5 minutes.
SELECT public.check_worker_heartbeat();
SELECT public.check_worker_heartbeat();
SELECT assert('no re-alert inside the realert window',
              (SELECT count(*) FROM public.sent_alerts) = 1);

-- ── 4. Still stale, past realert window → alerts again ────────────────────
UPDATE public.watchdog_config SET last_alerted_at = now() - interval '7 hours';
SELECT public.check_worker_heartbeat();
SELECT assert('re-alerts once the window has passed',
              (SELECT count(*) FROM public.sent_alerts) = 2);

-- ── 5. Recovery → sends the all-clear and clears the latch ────────────────
UPDATE public.mac_heartbeat SET last_seen = now();
SELECT public.check_worker_heartbeat();
SELECT assert('recovery sends an all-clear',
              (SELECT count(*) FROM public.sent_alerts) = 3);
SELECT assert('all-clear is low priority',
              (SELECT body->>'priority' FROM public.sent_alerts ORDER BY id DESC LIMIT 1) = '2');
SELECT assert('latch cleared on recovery',
              (SELECT last_alerted_at IS NULL FROM public.watchdog_config));

-- ── 6. Healthy and already clear → silent ─────────────────────────────────
SELECT public.check_worker_heartbeat();
SELECT public.check_worker_heartbeat();
SELECT assert('healthy worker produces no traffic',
              (SELECT count(*) FROM public.sent_alerts) = 3);

-- ── 7. A fresh outage after recovery alerts immediately ───────────────────
-- The latch must not suppress the NEXT outage; this is why recovery clears it.
UPDATE public.mac_heartbeat SET last_seen = now() - interval '30 minutes';
SELECT public.check_worker_heartbeat();
SELECT assert('a new outage alerts immediately after a recovery',
              (SELECT count(*) FROM public.sent_alerts) = 4);

-- ── 8. Disabled → inert regardless of state ───────────────────────────────
UPDATE public.watchdog_config SET enabled = false, last_alerted_at = NULL;
SELECT public.check_worker_heartbeat();
SELECT assert('disabled watchdog stays silent',
              (SELECT count(*) FROM public.sent_alerts) = 4);

-- ── 9. Just inside the stale threshold → not yet an outage ────────────────
UPDATE public.watchdog_config SET enabled = true, last_alerted_at = NULL;
UPDATE public.mac_heartbeat SET last_seen = now() - interval '14 minutes';
SELECT public.check_worker_heartbeat();
SELECT assert('14 minutes of silence is not yet an outage',
              (SELECT count(*) FROM public.sent_alerts) = 4);

UPDATE public.mac_heartbeat SET last_seen = now() - interval '16 minutes';
SELECT public.check_worker_heartbeat();
SELECT assert('16 minutes of silence is an outage',
              (SELECT count(*) FROM public.sent_alerts) = 5);

SELECT '✓ all watchdog tests passed' AS result;
