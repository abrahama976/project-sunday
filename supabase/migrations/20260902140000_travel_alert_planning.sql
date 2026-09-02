-- travel_alerts learns to remember a PLAN, not just a delivery.
--
-- The table was written to answer one question — "have they already been told
-- about this event?" — and travel_watch inserted a row only after a push
-- succeeded. That is right for retry: a failed notification should be sent
-- again rather than silently marked delivered.
--
-- But it left the job with no memory of anything it had worked out. An event
-- five hours away was therefore re-planned on every five-minute tick, roughly
-- sixty full TfNSW searches before the alert was ever due, and fifty-nine of
-- them changed nothing. The multi-strategy search makes each of those several
-- requests rather than one, so the waste stops being theoretical.
--
-- So the two meanings are split apart:
--
--   planned_at / planned_leave_at   what the last search worked out, and when
--   alerted_at                      when the push actually went out
--
-- `alerted_at` therefore has to become nullable — a row can now exist for an
-- event nobody has been told about yet. That is the point of the change.

ALTER TABLE public.travel_alerts
    ALTER COLUMN alerted_at DROP NOT NULL,
    ALTER COLUMN alerted_at DROP DEFAULT,
    ADD COLUMN IF NOT EXISTS planned_leave_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS planned_at       TIMESTAMPTZ;

-- Any row written under the old shape meant "already alerted", and the DEFAULT
-- now() it carried means alerted_at is already populated. Backfilling the
-- planning columns from it keeps such a row from looking unplanned and being
-- re-searched once on the next tick. A no-op on an empty table; correct if it
-- is not.
UPDATE public.travel_alerts
   SET planned_leave_at = COALESCE(planned_leave_at, leave_at),
       planned_at       = COALESCE(planned_at, alerted_at)
 WHERE alerted_at IS NOT NULL
   AND (planned_leave_at IS NULL OR planned_at IS NULL);

COMMENT ON COLUMN public.travel_alerts.planned_at IS
    'When travel_watch last searched for this event. Throttles re-planning.';
COMMENT ON COLUMN public.travel_alerts.planned_leave_at IS
    'The leave time that search produced, whether or not a push was sent.';
COMMENT ON COLUMN public.travel_alerts.alerted_at IS
    'When the push actually went out. NULL means planned but not yet told.';
