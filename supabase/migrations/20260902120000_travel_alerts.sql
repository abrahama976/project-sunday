-- travel_alerts — what travel_watch has already told you about.
--
-- The job recomputes on every scheduler tick, deliberately: a train running
-- late should move your alert rather than leave you with a stale one. Without
-- a record of what was already sent, that same property makes it push on every
-- tick as well.
--
-- `leave_at` is stored alongside `alerted_at` so the row says what was decided,
-- not merely that something was. A leave time that moved after the alert went
-- out is worth being able to see.

CREATE TABLE IF NOT EXISTS public.travel_alerts (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    -- The Google Calendar event id, not a local row: travel_watch reads
    -- calendar_events, which sync_calendar refreshes wholesale.
    event_id    TEXT NOT NULL,
    event_start TIMESTAMPTZ,
    leave_at    TIMESTAMPTZ,
    alerted_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One alert per event. This is the constraint that makes the job idempotent;
-- the code checks first, and this is what holds if two ticks ever overlap.
CREATE UNIQUE INDEX IF NOT EXISTS travel_alerts_user_event_idx
    ON public.travel_alerts (user_id, event_id);

CREATE INDEX IF NOT EXISTS travel_alerts_alerted_at_idx
    ON public.travel_alerts (alerted_at);

ALTER TABLE public.travel_alerts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS travel_alerts_owner ON public.travel_alerts;
CREATE POLICY travel_alerts_owner ON public.travel_alerts
    FOR ALL
    TO authenticated
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

-- Every 5 minutes: often enough that a delay moves the alert before you leave,
-- rare enough to be free. The job makes no model call, so this costs nothing
-- against the 250/day budget.
INSERT INTO public.scheduled_jobs (job_name, cron_expr, timezone, enabled, config)
VALUES ('travel_watch', '*/5 * * * *', 'Australia/Sydney', true,
        '{"description": "Push a leave-now alert before calendar events with a location"}'::jsonb)
ON CONFLICT (job_name) DO UPDATE
   SET cron_expr = EXCLUDED.cron_expr,
       timezone  = EXCLUDED.timezone,
       enabled   = true;
