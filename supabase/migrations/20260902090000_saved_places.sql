-- Saved places — the fixed locations Sunday can route from and to.
--
-- Deliberately NOT merged into `user_location`. That table holds ONE row per
-- user and is the *live* position, overwritten by POST /api/location whenever
-- the phone reports in. These are the standing ones — home, work, the places
-- you go every week — which never move and must survive a GPS update.
--
-- Without this, `travel_directions` had no origin to fall back on, so the model
-- had to stop and ask "where will you be coming from?" every single time.

CREATE TABLE IF NOT EXISTS public.saved_places (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    label       TEXT NOT NULL,
    address     TEXT NOT NULL,
    lat         DOUBLE PRECISION,
    lng         DOUBLE PRECISION,
    -- The origin used when nothing else is known and the GPS fix is stale.
    is_default  BOOLEAN NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One label per user: "home" means one place, so an upsert can target it.
CREATE UNIQUE INDEX IF NOT EXISTS saved_places_user_label_idx
    ON public.saved_places (user_id, lower(label));

-- At most one default per user. A partial unique index says that in the schema
-- rather than hoping every writer remembers to clear the old one.
CREATE UNIQUE INDEX IF NOT EXISTS saved_places_one_default_idx
    ON public.saved_places (user_id) WHERE is_default;

CREATE INDEX IF NOT EXISTS saved_places_user_id_idx
    ON public.saved_places (user_id);

ALTER TABLE public.saved_places ENABLE ROW LEVEL SECURITY;

CREATE POLICY saved_places_owner ON public.saved_places
    FOR ALL
    TO authenticated
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

DROP TRIGGER IF EXISTS saved_places_set_updated_at ON public.saved_places;
CREATE TRIGGER saved_places_set_updated_at
    BEFORE UPDATE ON public.saved_places
    FOR EACH ROW
    EXECUTE FUNCTION public.set_updated_at();
