-- nearby_services — the transit that actually exists where you start from.
--
-- Trip planning used to ask TfNSW one question and take its answer. One query
-- returns one corridor, so a place served by four different routes was only
-- ever offered one of them: the 343 to Central would surface and the 358 to
-- Mascot, the 306, and the metro simply never entered the pool. Ranking cannot
-- fix that, because the options were never generated.
--
-- So the boarding points are enumerated instead, and this is where they live:
-- one row per (stop, route, direction), refreshed weekly, and correctable.
--
-- `source` is the correctable part. A row you added or edited is marked 'user'
-- and discovery must never overwrite it — the API not knowing about a service
-- you catch every day should not mean Sunday forgets it every Sunday night.
-- `is_hidden` retires a route you would not take without deleting what was
-- found.
--
-- This is structured data: a route number, a destination, a frequency. It is
-- deliberately NOT free text, and nothing here is ever injected into a system
-- prompt — brain_directives remains the only thing that is, and it has its own
-- CHECK constraint forbidding tool-derived rows.

CREATE TABLE IF NOT EXISTS public.nearby_services (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,

    -- Which saved place these services are near. 'home' today; the column
    -- exists so a second place does not need a migration.
    place_label  TEXT NOT NULL DEFAULT 'home',

    stop_id      TEXT,
    stop_name    TEXT NOT NULL,
    stop_lat     DOUBLE PRECISION,
    stop_lng     DOUBLE PRECISION,

    -- TfNSW product class: 1 train, 2 metro, 4 light rail, 5 bus, 9 ferry.
    mode_class   INTEGER,
    route        TEXT NOT NULL,
    headsign     TEXT,

    -- Measured from the gaps between consecutive departures, not assumed.
    -- NULL when only one departure was visible: a made-up frequency is worse
    -- than an absent one, because it looks like knowledge.
    headway_min  INTEGER,
    walk_min     INTEGER,

    source       TEXT NOT NULL DEFAULT 'discovered'
                 CHECK (source IN ('discovered', 'user')),
    is_hidden    BOOLEAN NOT NULL DEFAULT false,

    refreshed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per service in a direction from a given stop. This is what the
-- refresh job upserts against.
CREATE UNIQUE INDEX IF NOT EXISTS nearby_services_unique_idx
    ON public.nearby_services (user_id, place_label, stop_name, route, COALESCE(headsign, ''));

-- The planner reads "everything usable near this place, nearest first".
CREATE INDEX IF NOT EXISTS nearby_services_lookup_idx
    ON public.nearby_services (user_id, place_label, is_hidden, walk_min);

ALTER TABLE public.nearby_services ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS nearby_services_owner ON public.nearby_services;
CREATE POLICY nearby_services_owner ON public.nearby_services
    FOR ALL
    TO authenticated
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

-- Weekly. The stops near a fixed address change on the scale of months, and
-- the job makes no model call, so this costs nothing against the 250/day cap.
-- Sunday 04:00 local: after the timetable changes that land over a weekend,
-- and long before anyone asks it for a trip.
INSERT INTO public.scheduled_jobs (job_name, cron_expr, timezone, enabled, config)
VALUES ('refresh_nearby_services', '0 4 * * 0', 'Australia/Sydney', true,
        '{"description": "Rediscover the stops, routes and frequencies near home"}'::jsonb)
ON CONFLICT (job_name) DO UPDATE
   SET cron_expr = EXCLUDED.cron_expr,
       timezone  = EXCLUDED.timezone,
       enabled   = true;
