-- Stop clearing the chat from destroying the traces.
--
-- agent_turns.message_id was declared ON DELETE CASCADE, so deleting a message
-- deleted every telemetry row for the run that answered it. Clearing the chat
-- therefore wiped the trace history — which already happened once, taking every
-- run recorded before 2026-09-02 with it.
--
-- Those traces are not incidental. They are what diagnosed the trip_plan
-- failure: the tool arguments and results sitting in this table are the only
-- reason it was possible to see that "Sydney → Sans Souci" returned zero
-- journeys, and therefore that the bug was address resolution rather than
-- routing. Destroying them on a routine UI action is the wrong trade.
--
-- SET NULL rather than dropping the reference: a run whose message is gone is
-- still a real run worth reading. The trace view already renders it as
-- "(background run — no message)" / "(message deleted)", so nothing on the
-- front end changes.
--
-- The column is already nullable — background runs have no message — so no
-- backfill is needed and existing orphans stay valid.

ALTER TABLE public.agent_turns
    DROP CONSTRAINT IF EXISTS agent_turns_message_id_fkey;

ALTER TABLE public.agent_turns
    ADD CONSTRAINT agent_turns_message_id_fkey
    FOREIGN KEY (message_id) REFERENCES public.messages(id)
    ON DELETE SET NULL;

COMMENT ON COLUMN public.agent_turns.message_id IS
    'The chat message this run answered, or NULL for a background run or one '
    'whose message was deleted. SET NULL, never CASCADE: the trace outlives '
    'the message.';
