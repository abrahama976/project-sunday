-- Travel planning the app can drive, and a plan that survives being answered.
--
-- Two problems, one shape.
--
-- 1. The web app runs on Vercel and the worker runs on a Mac. Nothing on
--    Vercel can reach it, so every feature that needs the worker goes through
--    this database and a poll loop — `messages`, `action_queue` and
--    `one_off_reminders` all work this way. Trip planning from a UI is the
--    same problem and gets the same answer: `travel_requests` is the inbox.
--
-- 2. `plan_journeys` builds a genuinely rich answer — ranked options, each one
--    tagged with the strategy that found it, plus everything the plausibility
--    gate threw away and *why* — and then `format_journeys` renders it to a
--    string and the structure is lost. That single fact is why there can be no
--    travel UI, why a failure collapses to one summary sentence instead of the
--    per-option reasons that exist, and why nothing can learn from where the
--    user actually goes. `travel_plans` keeps it.
--
-- Deliberately NOT free text, and nothing here is ever injected into a system
-- prompt: `brain_directives` remains the only thing that is, and it keeps its
-- CHECK constraint forbidding tool-derived rows. A destination the user typed
-- is data about a journey, not an instruction.

-- ── The inbox ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.travel_requests (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,

    origin_text        TEXT,          -- NULL means "from wherever I am"
    destination_text   TEXT NOT NULL,
    arrive_by          TIMESTAMPTZ,
    depart_at          TIMESTAMPTZ,

    -- Two flags, not one. "I have a car I drive" and "somebody can drop me"
    -- are different permissions: with a lift there is no car to leave at a
    -- station, so park-and-ride is as wrong for you as parking at a bus stop.
    car_available      BOOLEAN NOT NULL DEFAULT false,
    drop_off_available BOOLEAN NOT NULL DEFAULT false,

    status        TEXT NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending', 'planning', 'done', 'failed')),
    plan_id       uuid,               -- FK added after travel_plans exists
    error         TEXT,

    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at    TIMESTAMPTZ,
    completed_at  TIMESTAMPTZ
);

-- ── The answer, kept ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.travel_plans (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,

    -- SET NULL rather than CASCADE, for the same reason agent_turns keeps its
    -- traces: deleting the request that asked should not destroy the evidence
    -- of what was answered.
    request_id    uuid REFERENCES public.travel_requests(id) ON DELETE SET NULL,

    -- What the user said, and what it was taken to mean. Both, because the gap
    -- between them is where "Sans Souci" became Narrabri.
    origin_text        TEXT,
    origin_label       TEXT,
    origin_lat         DOUBLE PRECISION,
    origin_lng         DOUBLE PRECISION,
    destination_text   TEXT,
    destination_label  TEXT,
    destination_lat    DOUBLE PRECISION,
    destination_lng    DOUBLE PRECISION,

    arrive_by          TIMESTAMPTZ,
    depart_at          TIMESTAMPTZ,
    car_available      BOOLEAN NOT NULL DEFAULT false,
    drop_off_available BOOLEAN NOT NULL DEFAULT false,

    -- Ranked, best first. Each carries its strategy, so the UI can say whether
    -- an option came from the baseline query, a boarding point, a park-and-ride
    -- or a lift — which is also the only way to see whether the fan-out ran.
    options       JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- What the gate rejected, each with its reason. Today these are summarised
    -- into one sentence and discarded; keeping them is what lets an answer of
    -- "nothing works" explain itself.
    rejected      JSONB NOT NULL DEFAULT '[]'::jsonb,

    drive         JSONB,              -- {minutes, km} door to door, or NULL
    state         TEXT NOT NULL DEFAULT 'ok',
    reason        TEXT,               -- why, when state is not 'ok'

    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.travel_requests
    DROP CONSTRAINT IF EXISTS travel_requests_plan_id_fkey;
ALTER TABLE public.travel_requests
    ADD CONSTRAINT travel_requests_plan_id_fkey
    FOREIGN KEY (plan_id) REFERENCES public.travel_plans(id) ON DELETE SET NULL;

-- The worker's poll: oldest unanswered request first.
CREATE INDEX IF NOT EXISTS travel_requests_pending_idx
    ON public.travel_requests (status, created_at)
    WHERE status = 'pending';

-- The page's read: my recent plans, newest first.
CREATE INDEX IF NOT EXISTS travel_plans_recent_idx
    ON public.travel_plans (user_id, created_at DESC);

-- What the learning job aggregates: where has this person actually been going.
-- A destination planned repeatedly is a place worth offering to save, and the
-- offer goes through action_queue like every other write.
CREATE INDEX IF NOT EXISTS travel_plans_destination_idx
    ON public.travel_plans (user_id, destination_label);

ALTER TABLE public.travel_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.travel_plans    ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS travel_requests_owner ON public.travel_requests;
CREATE POLICY travel_requests_owner ON public.travel_requests
    FOR ALL TO authenticated
    USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS travel_plans_owner ON public.travel_plans;
CREATE POLICY travel_plans_owner ON public.travel_plans
    FOR ALL TO authenticated
    USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
