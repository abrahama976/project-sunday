-- A trace must outlive the message it answered.
--
-- Clearing the chat used to delete the telemetry with it, because message_id
-- was ON DELETE CASCADE. That is the data which diagnosed the trip_plan bug,
-- so the retention is worth a test rather than a comment.

CREATE OR REPLACE FUNCTION assert(label text, cond boolean) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    IF cond THEN RAISE NOTICE '  ok  %', label;
    ELSE RAISE EXCEPTION 'FAIL: %', label;
    END IF;
END;
$$;

INSERT INTO auth.users (id) VALUES ('11111111-1111-1111-1111-111111111111')
ON CONFLICT DO NOTHING;

DELETE FROM public.agent_turns;
DELETE FROM public.messages;

INSERT INTO public.messages (id) VALUES ('22222222-2222-2222-2222-222222222222');

INSERT INTO public.agent_turns (run_id, user_id, message_id, step_index, type, tool_name)
VALUES ('33333333-3333-3333-3333-333333333333',
        '11111111-1111-1111-1111-111111111111',
        '22222222-2222-2222-2222-222222222222',
        0, 'tool_call', 'trip_plan');

SELECT assert('a run is linked to its message',
    (SELECT message_id IS NOT NULL FROM public.agent_turns WHERE tool_name = 'trip_plan'));

-- Clearing the chat.
DELETE FROM public.messages WHERE id = '22222222-2222-2222-2222-222222222222';

SELECT assert('the trace survives its message being deleted',
    (SELECT count(*) = 1 FROM public.agent_turns WHERE tool_name = 'trip_plan'));
SELECT assert('...and is orphaned rather than destroyed',
    (SELECT message_id IS NULL FROM public.agent_turns WHERE tool_name = 'trip_plan'));

-- The constraint itself, so a later migration cannot quietly restore CASCADE.
SELECT assert('the foreign key is SET NULL, not CASCADE',
    (SELECT pg_get_constraintdef(oid) LIKE '%ON DELETE SET NULL%'
       FROM pg_constraint
      WHERE conrelid = 'public.agent_turns'::regclass
        AND conname = 'agent_turns_message_id_fkey'));

DO $$ BEGIN RAISE NOTICE ' ✓ all agent_turns retention tests passed'; END $$;
