-- Make user_location upsertable, and make the worker able to find the row.
--
-- Three faults, all in the same short path, and all of them silent:
--
-- 1. `/api/location` upserted with `onConflict: "id"`, against a column whose
--    default is gen_random_uuid(). A fresh uuid never conflicts, so every POST
--    INSERTED rather than updated and the table would grow a row per fix.
--
-- 2. It never wrote `user_id`. `resolve_origin` reads
--    `.eq("user_id", user_id)`, so even a successful write was invisible to
--    the worker — the live-location branch could not have fired whatever the
--    phone sent.
--
-- 3. `user_id` carried only a NON-unique index, so switching the upsert to it
--    would have failed with 42P10 — the same error, on the same shape of
--    mistake, as nearby_services in #39. PostgREST emits a plain
--    `ON CONFLICT (user_id)` and Postgres needs a real unique constraint to
--    match it.
--
-- The table is empty, so NOT NULL needs no backfill. It has to be NOT NULL as
-- well as unique: a unique index permits many NULLs, which would let exactly
-- the duplicate rows this is meant to prevent back in through the one value
-- the old code was writing.

DELETE FROM public.user_location WHERE user_id IS NULL;

ALTER TABLE public.user_location
    ALTER COLUMN user_id SET NOT NULL;

ALTER TABLE public.user_location
    DROP CONSTRAINT IF EXISTS user_location_user_unique;
ALTER TABLE public.user_location
    ADD CONSTRAINT user_location_user_unique UNIQUE (user_id);

COMMENT ON CONSTRAINT user_location_user_unique ON public.user_location IS
    'One current fix per user, and the key POST /api/location upserts against. '
    'A plain column constraint rather than an index on an expression, because '
    'PostgREST can only target the former — see migration 20260903200000.';
