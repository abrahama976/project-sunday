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
SELECT assert('the upsert key exists',
    EXISTS (SELECT 1 FROM pg_indexes
             WHERE schemaname = 'public' AND tablename = 'nearby_services'
               AND indexname = 'nearby_services_unique_idx'));

INSERT INTO public.nearby_services
    (user_id, stop_name, route, headsign, mode_class, headway_min, walk_min)
VALUES ('11111111-1111-1111-1111-111111111111', 'Gardeners Rd', '343', 'Central', 5, 12, 4)
ON CONFLICT (user_id, place_label, stop_name, route, COALESCE(headsign, ''))
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
