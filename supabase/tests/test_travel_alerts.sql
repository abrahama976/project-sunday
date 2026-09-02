-- travel_alerts, after the planning columns were split out of the delivery
-- record. These are the properties travel_watch depends on to avoid both
-- re-planning every tick and pushing the same alert twice.

CREATE OR REPLACE FUNCTION assert(label text, cond boolean) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    IF cond THEN RAISE NOTICE '  ok  %', label;
    ELSE RAISE EXCEPTION 'FAIL: %', label;
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION assert_rejects(label text, stmt text) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    BEGIN
        EXECUTE stmt;
    EXCEPTION WHEN others THEN
        RAISE NOTICE '  ok  %', label;
        RETURN;
    END;
    RAISE EXCEPTION 'FAIL: % — statement was accepted but should have been rejected', label;
END;
$$;

INSERT INTO auth.users (id) VALUES ('11111111-1111-1111-1111-111111111111')
ON CONFLICT DO NOTHING;

DELETE FROM public.travel_alerts;

-- The whole point of the migration: a row can now exist for an event nobody
-- has been told about yet. Under the old shape alerted_at was NOT NULL with a
-- default of now(), so merely recording a plan claimed a push had happened.
INSERT INTO public.travel_alerts (user_id, event_id, planned_leave_at, planned_at)
VALUES ('11111111-1111-1111-1111-111111111111', 'evt-planned',
        now() + interval '2 hours', now());

SELECT assert('a plan can be recorded without an alert',
    (SELECT alerted_at IS NULL FROM public.travel_alerts WHERE event_id = 'evt-planned'));

SELECT assert('...and it remembers the leave time it worked out',
    (SELECT planned_leave_at IS NOT NULL FROM public.travel_alerts WHERE event_id = 'evt-planned'));

-- travel_watch upserts on (user_id, event_id), so this index is not an
-- optimisation — it is what makes the upsert legal and the job idempotent.
SELECT assert('the unique index the upsert targets exists',
    EXISTS (SELECT 1 FROM pg_indexes
             WHERE schemaname = 'public'
               AND tablename = 'travel_alerts'
               AND indexname = 'travel_alerts_user_event_idx'));

SELECT assert_rejects(
    'the same event cannot be recorded twice',
    $q$INSERT INTO public.travel_alerts (user_id, event_id)
       VALUES ('11111111-1111-1111-1111-111111111111', 'evt-planned')$q$
);

-- The upsert path: a second plan for the same event replaces the first rather
-- than failing, which is how a moved leave time is recorded.
INSERT INTO public.travel_alerts (user_id, event_id, planned_leave_at, planned_at)
VALUES ('11111111-1111-1111-1111-111111111111', 'evt-planned',
        now() + interval '3 hours', now())
ON CONFLICT (user_id, event_id) DO UPDATE
   SET planned_leave_at = EXCLUDED.planned_leave_at,
       planned_at       = EXCLUDED.planned_at;

SELECT assert('a re-plan moves the leave time in place',
    (SELECT count(*) = 1 FROM public.travel_alerts WHERE event_id = 'evt-planned'));

-- Marking the push as sent is a separate step, so a failed notification stays
-- retryable instead of being silently marked delivered.
UPDATE public.travel_alerts SET alerted_at = now() WHERE event_id = 'evt-planned';
SELECT assert('an alert can be marked sent afterwards',
    (SELECT alerted_at IS NOT NULL FROM public.travel_alerts WHERE event_id = 'evt-planned'));

-- The alert is meaningless without the user it was for.
DELETE FROM auth.users WHERE id = '11111111-1111-1111-1111-111111111111';
SELECT assert('deleting the user takes their alerts with them',
    (SELECT count(*) = 0 FROM public.travel_alerts));

DO $$ BEGIN RAISE NOTICE ' ✓ all travel_alerts tests passed'; END $$;
