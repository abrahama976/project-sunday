-- health_logs: that the fix migration meets legacy data correctly, and that the
-- upsert key is one the CLIENT can actually name.
--
-- The last point is the whole reason this file exists. `nearby_services` had a
-- unique EXPRESSION index, and a SQL test asserted that index existed — which
-- was true, and useless, because PostgREST emits a plain `ON CONFLICT (a, b)`
-- that Postgres cannot match to an expression. The upsert failed with 42P10 on
-- every row for a week while the test stayed green. `user_location` repeated
-- it. This table was the third.
--
-- So the assertions below issue the upsert in the shape the client sends, and
-- check for a pg_constraint row rather than an index.

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

-- ── what the migration did to the legacy rows ────────────────────────────────

SELECT assert('every legacy row was adopted by the one profile',
    (SELECT count(*) = 0 FROM public.health_logs WHERE user_id IS NULL));

SELECT assert('the two same-day water taps merged into one row',
    (SELECT count(*) = 1 FROM public.health_logs
     WHERE log_date = DATE '2026-06-09' AND metric = 'water'));

-- Merged, not deduplicated: 250 + 250. Keeping only the first would silently
-- halve a day's total, which is worse than the duplicate rows were.
SELECT assert('...carrying the SUM of both, not just one of them',
    (SELECT value = 500 FROM public.health_logs
     WHERE log_date = DATE '2026-06-09' AND metric = 'water'));

SELECT assert('a meal on the same day was not merged into the water row',
    (SELECT count(*) = 2 FROM public.health_logs
     WHERE log_date = DATE '2026-06-09' AND metric = 'meal'));

SELECT assert('breakfast and lunch stayed distinct rows',
    (SELECT count(DISTINCT meal_type) = 2 FROM public.health_logs
     WHERE log_date = DATE '2026-06-09' AND metric = 'meal'));

SELECT assert('a row on another day was left alone',
    (SELECT value = 250 FROM public.health_logs
     WHERE log_date = DATE '2026-06-06' AND metric = 'water'));

SELECT assert('NULL meal_type became the empty string',
    (SELECT count(*) = 0 FROM public.health_logs WHERE meal_type IS NULL));

-- ── the key, in the shape PostgREST sends ────────────────────────────────────

-- A plain unique CONSTRAINT, not an expression index. This is the assertion the
-- nearby_services test got wrong.
SELECT assert('the upsert key is a real constraint on plain columns',
    EXISTS (SELECT 1 FROM pg_constraint
            WHERE conrelid = 'public.health_logs'::regclass
              AND conname = 'health_logs_user_date_metric_meal_unique'
              AND contype = 'u'));

SELECT assert('the old expression index is gone',
    NOT EXISTS (SELECT 1 FROM pg_indexes
                WHERE tablename = 'health_logs'
                  AND indexdef LIKE '%COALESCE%'));

-- The actual client call. Fails with 42P10 if the key is not nameable.
INSERT INTO public.health_logs (user_id, log_date, metric, meal_type, value, source)
VALUES ('c0ffee00-0000-4000-8000-000000000001', DATE '2026-09-05', 'water', '', 250, 'manual')
ON CONFLICT (user_id, log_date, metric, meal_type)
DO UPDATE SET value = EXCLUDED.value;

INSERT INTO public.health_logs (user_id, log_date, metric, meal_type, value, source)
VALUES ('c0ffee00-0000-4000-8000-000000000001', DATE '2026-09-05', 'water', '', 500, 'manual')
ON CONFLICT (user_id, log_date, metric, meal_type)
DO UPDATE SET value = EXCLUDED.value;

SELECT assert('the client-shaped upsert updates in place rather than duplicating',
    (SELECT count(*) = 1 FROM public.health_logs
     WHERE log_date = DATE '2026-09-05' AND metric = 'water'));

SELECT assert('...and the second tap wins',
    (SELECT value = 500 FROM public.health_logs
     WHERE log_date = DATE '2026-09-05' AND metric = 'water'));

-- Two meals of different types on the same day are two rows, not a conflict.
INSERT INTO public.health_logs (user_id, log_date, metric, meal_type, value, source)
VALUES ('c0ffee00-0000-4000-8000-000000000001', DATE '2026-09-05', 'meal', 'lunch',  0, 'manual'),
       ('c0ffee00-0000-4000-8000-000000000001', DATE '2026-09-05', 'meal', 'dinner', 0, 'manual')
ON CONFLICT (user_id, log_date, metric, meal_type) DO NOTHING;

SELECT assert('lunch and dinner coexist on one day',
    (SELECT count(*) = 2 FROM public.health_logs
     WHERE log_date = DATE '2026-09-05' AND metric = 'meal'));

-- ── the hole that let the constraint sit inert ───────────────────────────────

-- This is what actually kept the rule from applying for three months: a unique
-- index permits any number of NULLs, so a NULL user_id exempted every row.
SELECT assert_rejects(
    'a row with no user is rejected outright',
    $q$INSERT INTO public.health_logs (log_date, metric, value, source)
       VALUES (DATE '2026-09-05', 'steps', 100, 'manual')$q$
);

SELECT assert_rejects(
    'a NULL meal_type is rejected',
    $q$INSERT INTO public.health_logs (user_id, log_date, metric, meal_type, value, source)
       VALUES ('c0ffee00-0000-4000-8000-000000000001', DATE '2026-09-07', 'meal', NULL, 0, 'manual')$q$
);

-- A data-modifying statement has to sit in a CTE; it is not a subquery.
WITH inserted AS (
    INSERT INTO public.health_logs (user_id, log_date, metric, value, source)
    VALUES ('c0ffee00-0000-4000-8000-000000000001', DATE '2026-09-08', 'steps', 4000, 'manual')
    RETURNING meal_type
)
SELECT assert('an omitted meal_type defaults to the empty string, not NULL',
              (SELECT meal_type = '' FROM inserted));

SELECT assert_rejects(
    'an unknown meal_type is still rejected',
    $q$INSERT INTO public.health_logs (user_id, log_date, metric, meal_type, value, source)
       VALUES ('c0ffee00-0000-4000-8000-000000000001', DATE '2026-09-09', 'meal', 'brunch', 0, 'manual')$q$
);

-- CASCADE, not SET NULL. SET NULL would put the rows straight back into the
-- state this whole migration exists to clear up.
DELETE FROM public.user_profile WHERE user_id = 'c0ffee00-0000-4000-8000-000000000001';
DELETE FROM auth.users WHERE id = 'c0ffee00-0000-4000-8000-000000000001';

SELECT assert('deleting the user takes their health history with them',
    (SELECT count(*) = 0 FROM public.health_logs));

DO $$ BEGIN RAISE NOTICE '  ✓ all health_logs tests passed'; END $$;
