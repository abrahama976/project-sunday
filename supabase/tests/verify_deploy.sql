-- Post-deploy verification. Read-only — safe to run any time.
--
-- Checks the actual schema and data rather than the migration ledger: a
-- migration recorded as applied that did not do what it claimed is exactly the
-- drift this project has already been bitten by.
--
-- Paste into the Supabase SQL editor. Every row should read PASS, except the
-- heartbeat freshness row while the worker is stopped.

SELECT * FROM (

-- ── Phase 0 migrations ────────────────────────────────────────────────────
SELECT 1 AS n, 'mac_heartbeat.status column' AS check,
       CASE WHEN EXISTS (
           SELECT 1 FROM information_schema.columns
            WHERE table_schema='public' AND table_name='mac_heartbeat'
              AND column_name='status')
       THEN 'PASS' ELSE 'FAIL' END AS status,
       'created by 20260828120000' AS detail

UNION ALL
-- Settles whether heartbeat writes have been failing all along. If last_seen
-- predates the column being added, the worker was writing to a column that did
-- not exist and every write threw.
SELECT 2, 'heartbeat last_seen',
       CASE WHEN (SELECT last_seen FROM public.mac_heartbeat WHERE id=1)
                 > NOW() - INTERVAL '15 minutes'
            THEN 'PASS' ELSE 'STALE (expected while the worker is stopped)' END,
       COALESCE((SELECT last_seen::text FROM public.mac_heartbeat WHERE id=1), 'no row')

UNION ALL
SELECT 3, 'pg_net installed',
       CASE WHEN EXISTS (SELECT 1 FROM pg_extension WHERE extname='pg_net')
            THEN 'PASS' ELSE 'FAIL — enable under Database → Extensions' END,
       COALESCE((SELECT extversion FROM pg_extension WHERE extname='pg_net'), '-')

UNION ALL
SELECT 4, 'pg_cron installed',
       CASE WHEN EXISTS (SELECT 1 FROM pg_extension WHERE extname='pg_cron')
            THEN 'PASS' ELSE 'FAIL' END,
       COALESCE((SELECT extversion FROM pg_extension WHERE extname='pg_cron'), '-')

UNION ALL
SELECT 5, 'watchdog cron job scheduled',
       CASE WHEN EXISTS (
           SELECT 1 FROM cron.job WHERE jobname='worker-heartbeat-watchdog' AND active)
       THEN 'PASS' ELSE 'FAIL' END,
       COALESCE((SELECT schedule FROM cron.job
                  WHERE jobname='worker-heartbeat-watchdog'), 'not scheduled')

UNION ALL
-- The watchdog is inert until this is set. Migrations deliberately do not set
-- it: an ntfy topic is public, so it does not belong in git.
SELECT 6, 'watchdog ARMED (ntfy topic)',
       CASE WHEN COALESCE((SELECT ntfy_topic FROM public.watchdog_config WHERE id=1),'') <> ''
            THEN 'PASS' ELSE 'NOT ARMED — see step 2 below' END,
       CASE WHEN COALESCE((SELECT ntfy_topic FROM public.watchdog_config WHERE id=1),'') <> ''
            THEN 'topic set, enabled=' ||
                 (SELECT enabled::text FROM public.watchdog_config WHERE id=1)
            ELSE 'no topic' END

-- ── Scheduler timezones ───────────────────────────────────────────────────
UNION ALL
SELECT 7, 'meal_checkin schedule',
       CASE WHEN EXISTS (SELECT 1 FROM public.scheduled_jobs
                          WHERE job_name='meal_checkin'
                            AND cron_expr='0 13,19 * * *'
                            AND timezone='Australia/Sydney')
            THEN 'PASS' ELSE 'FAIL' END,
       COALESCE((SELECT cron_expr || '  ' || timezone FROM public.scheduled_jobs
                  WHERE job_name='meal_checkin'), 'missing')

UNION ALL
SELECT 8, 'daily_brief schedule',
       CASE WHEN EXISTS (SELECT 1 FROM public.scheduled_jobs
                          WHERE job_name='daily_brief'
                            AND cron_expr='0 8 * * *'
                            AND timezone='Australia/Sydney')
            THEN 'PASS' ELSE 'FAIL' END,
       COALESCE((SELECT cron_expr || '  ' || timezone FROM public.scheduled_jobs
                  WHERE job_name='daily_brief'), 'missing')

UNION ALL
SELECT 9, 'cold_storage_archive schedule',
       CASE WHEN EXISTS (SELECT 1 FROM public.scheduled_jobs
                          WHERE job_name='cold_storage_archive'
                            AND timezone='Australia/Sydney')
            THEN 'PASS' ELSE 'FAIL' END,
       COALESCE((SELECT cron_expr || '  ' || timezone FROM public.scheduled_jobs
                  WHERE job_name='cold_storage_archive'), 'missing')

-- ── The learning brain ────────────────────────────────────────────────────
UNION ALL
SELECT 10, 'brain_directives table',
       CASE WHEN EXISTS (SELECT 1 FROM information_schema.tables
                          WHERE table_schema='public' AND table_name='brain_directives')
            THEN 'PASS' ELSE 'FAIL' END,
       (SELECT count(*)::text || ' directive(s)' FROM public.brain_directives)

UNION ALL
-- The prompt-injection guard. This must be enforced by the database, not only
-- by the executor, or a future code path can bypass it.
SELECT 11, 'brain source CHECK constraint',
       CASE WHEN EXISTS (
           SELECT 1 FROM pg_constraint
            WHERE conname='brain_directives_source_check')
       THEN 'PASS' ELSE 'FAIL' END,
       'rejects source=tool'

UNION ALL
SELECT 12, 'agent_turns ready for the loop',
       CASE WHEN EXISTS (SELECT 1 FROM information_schema.tables
                          WHERE table_schema='public' AND table_name='agent_turns')
            THEN 'PASS' ELSE 'FAIL' END,
       (SELECT count(*)::text || ' row(s) — 0 until PR #24 merges and the worker runs'
          FROM public.agent_turns)

) checks ORDER BY n;
