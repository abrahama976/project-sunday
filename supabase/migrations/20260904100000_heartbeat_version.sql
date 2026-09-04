-- Let the worker say which commit it is running.
--
-- Four fixes were merged and the answers in chat did not change. The natural
-- reading was that the fixes were wrong; the truth was that the worker was
-- still on an older commit, and nothing could say so. It had to be inferred
-- backwards from model behaviour — a 2024 date the new prompt would have
-- prevented, a past time the new guard would have refused, a 500 km
-- destination the new gate would have rejected.
--
-- One column ends that class of question. `is this deployed` becomes a lookup
-- rather than a deduction.
--
-- Nullable with no default: a worker that predates this migration writes no
-- version, and NULL should read as "did not say", not as a version.

ALTER TABLE public.mac_heartbeat
    ADD COLUMN IF NOT EXISTS version text;

COMMENT ON COLUMN public.mac_heartbeat.version IS
    'Short git sha of the running worker checkout, plus +dirty and branch when '
    'they apply. Written every heartbeat by apps/worker/version.py. NULL means '
    'the worker did not report one.';
