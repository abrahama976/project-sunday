-- nearby_services: the properties trip planning and the weekly refresh rely on.
-- The one that matters most is that discovery cannot overwrite what you told it.

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

DELETE FROM public.nearby_services;

INSERT INTO public.nearby_services
    (user_id, stop_name, route, headsign, mode_class, headway_min, walk_min)
VALUES ('11111111-1111-1111-1111-111111111111', 'Gardeners Rd', '343', 'Central', 5, 10, 4);

SELECT assert('a discovered service defaults to source=discovered',
    (SELECT source = 'discovered' FROM public.nearby_services WHERE route = '343'));

SELECT assert('...and is visible by default',
    (SELECT is_hidden = false FROM public.nearby_services WHERE route = '343'));

-- Only two sources exist. Anything else would quietly change what discovery is
-- allowed to overwrite.
SELECT assert_rejects(
    'an unknown source is rejected',
    $q$INSERT INTO public.nearby_services (user_id, stop_name, route, source)
       VALUES ('11111111-1111-1111-1111-111111111111', 'X', 'Y', 'guessed')$q$
);

-- The refresh job upserts on this key; without it every weekly run would
-- duplicate the whole inventory.
--
-- Asserted as a *constraint*, not merely an index. An expression index is a
-- perfectly good unique key from psql and is unreachable from PostgREST, which
-- is the difference that kept this table empty for a week. pg_constraint only
-- lists the plain-column form, so this assertion cannot pass on the shape the
-- client cannot use.
SELECT assert('the upsert key is a plain-column unique constraint',
    EXISTS (SELECT 1 FROM pg_constraint
             WHERE conrelid = 'public.nearby_services'::regclass
               AND conname  = 'nearby_services_unique'
               AND contype  = 'u'));

SELECT assert('the old expression index is gone',
    NOT EXISTS (SELECT 1 FROM pg_indexes
                 WHERE schemaname = 'public' AND tablename = 'nearby_services'
                   AND indexname = 'nearby_services_unique_idx'));

-- THE TEST THAT WAS MISSING.
--
-- supabase-py's `.upsert(row, on_conflict="user_id,place_label,stop_name,
-- route,headsign")` reaches Postgres as exactly this: a plain column list. The
-- previous version of this test wrote `COALESCE(headsign, '')` here, matching
-- the index rather than the caller, so it passed against a schema on which
-- every real write failed with 42P10. Write it the way the client writes it.
INSERT INTO public.nearby_services
    (user_id, stop_name, route, headsign, mode_class, headway_min, walk_min)
VALUES ('11111111-1111-1111-1111-111111111111', 'Gardeners Rd', '343', 'Central', 5, 12, 4)
ON CONFLICT (user_id, place_label, stop_name, route, headsign)
DO UPDATE SET headway_min = EXCLUDED.headway_min;

SELECT assert('re-running discovery updates in place rather than duplicating',
    (SELECT count(*) = 1 FROM public.nearby_services WHERE route = '343'));
SELECT assert('...and the newer frequency wins',
    (SELECT headway_min = 12 FROM public.nearby_services WHERE route = '343'));

-- The same route in the other direction is a different service: it decides
-- which side of the road you stand on.
INSERT INTO public.nearby_services (user_id, stop_name, route, headsign, walk_min)
VALUES ('11111111-1111-1111-1111-111111111111', 'Gardeners Rd', '343', 'Kingsford', 4);
SELECT assert('the same route in the other direction is its own row',
    (SELECT count(*) = 2 FROM public.nearby_services WHERE route = '343'));

-- '' is what "no destination shown" means, and it has to be a real value: two
-- NULLs do not conflict with each other, so a nullable headsign under a plain
-- unique key would let the weekly run duplicate every unlabelled service.
SELECT assert_rejects(
    'a NULL headsign is rejected',
    $q$INSERT INTO public.nearby_services (user_id, stop_name, route, headsign)
       VALUES ('11111111-1111-1111-1111-111111111111', 'Gardeners Rd', '999', NULL)$q$
);

INSERT INTO public.nearby_services (user_id, stop_name, route, walk_min)
VALUES ('11111111-1111-1111-1111-111111111111', 'Gardeners Rd', '999', 7);
SELECT assert('an omitted headsign becomes the empty string, not NULL',
    (SELECT headsign = '' FROM public.nearby_services WHERE route = '999'));

-- And re-discovering that same unlabelled service updates it rather than
-- adding a second copy — the case the COALESCE was there to cover.
INSERT INTO public.nearby_services (user_id, stop_name, route, walk_min)
VALUES ('11111111-1111-1111-1111-111111111111', 'Gardeners Rd', '999', 9)
ON CONFLICT (user_id, place_label, stop_name, route, headsign)
DO UPDATE SET walk_min = EXCLUDED.walk_min;
SELECT assert('an unlabelled service still upserts in place',
    (SELECT count(*) = 1 AND max(walk_min) = 9
       FROM public.nearby_services WHERE route = '999'));

-- A route you added yourself, that the API does not report.
INSERT INTO public.nearby_services (user_id, stop_name, route, headsign, walk_min, source)
VALUES ('11111111-1111-1111-1111-111111111111', 'Gardeners Rd', '306', 'Sans Souci', 6, 'user');

-- Discovery only ever writes source='discovered', so a row you own is out of
-- its reach. This is what stops Sunday forgetting your own correction every
-- Sunday night.
UPDATE public.nearby_services
   SET headway_min = 99
 WHERE route = '306' AND source = 'discovered';

SELECT assert('a row you edited is untouched by discovery',
    (SELECT headway_min IS NULL FROM public.nearby_services WHERE route = '306'));

UPDATE public.nearby_services SET is_hidden = true WHERE route = '306';
SELECT assert('a route can be retired without deleting what was found',
    (SELECT is_hidden FROM public.nearby_services WHERE route = '306'));

DELETE FROM auth.users WHERE id = '11111111-1111-1111-1111-111111111111';
SELECT assert('deleting the user takes their services with them',
    (SELECT count(*) = 0 FROM public.nearby_services));

DO $$ BEGIN RAISE NOTICE ' ✓ all nearby_services tests passed'; END $$;
