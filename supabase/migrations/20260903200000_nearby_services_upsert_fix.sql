-- Make the nearby_services upsert key one PostgREST can actually target.
--
-- The weekly refresh job has never written a single row. It discovers the 306,
-- 309, 343, 358 and N20 near home, then fails on every one of them with
--
--     42P10: there is no unique or exclusion constraint matching the
--            ON CONFLICT specification
--
-- so `nearby_services` stays empty and boarding-point search — the whole reason
-- the table exists — has nothing to read. Trip planning silently fell back to
-- the single-corridor behaviour the table was added to replace.
--
-- The cause is a mismatch in *shape*, not in columns. The key was created as an
-- expression index:
--
--     (user_id, place_label, stop_name, route, COALESCE(headsign, ''))
--
-- supabase-py's `on_conflict="user_id,place_label,stop_name,route,headsign"`
-- becomes a plain `ON CONFLICT (user_id, …, headsign)`, and Postgres will not
-- match a plain column list to an indexed expression. Both forms are correct
-- SQL; only one of them is reachable from the client.
--
-- The COALESCE existed to make NULL and '' collide, since two NULL headsigns
-- do not conflict with each other under a plain unique index and every weekly
-- run would duplicate those rows. Rather than keep the expression, remove the
-- NULL: discovery already writes '' for "no destination shown" (jobs.py strips
-- into a string), so the column can say what was always true.
--
-- The SQL test that should have caught this asserted the *expression* form of
-- ON CONFLICT, which is legal from psql and is not what the client sends. Its
-- replacement issues the upsert the way PostgREST does.

ALTER TABLE public.nearby_services
    ALTER COLUMN headsign SET DEFAULT '';

-- No backfill guard needed beyond this: the table is empty in production, for
-- exactly the reason this migration exists. Written anyway so the migration is
-- safe to run against a database where some rows did land.
UPDATE public.nearby_services SET headsign = '' WHERE headsign IS NULL;

ALTER TABLE public.nearby_services
    ALTER COLUMN headsign SET NOT NULL;

DROP INDEX IF EXISTS public.nearby_services_unique_idx;

-- A named constraint rather than a bare unique index: it is the thing the
-- client names, so it should be visible in \d and in pg_constraint.
ALTER TABLE public.nearby_services
    DROP CONSTRAINT IF EXISTS nearby_services_unique;
ALTER TABLE public.nearby_services
    ADD CONSTRAINT nearby_services_unique
    UNIQUE (user_id, place_label, stop_name, route, headsign);
