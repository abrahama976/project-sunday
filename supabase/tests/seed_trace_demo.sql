-- Seed one synthetic agent run, so /traces can be looked at before the worker
-- is back writing real ones.
--
-- Unlike everything else in this directory, this is NOT a test — it WRITES, and
-- it is meant to be run against the real project (SQL editor, or psql against
-- the pooler). Run the teardown at the bottom when you are done looking.
--
-- The run it seeds is the one Phase 1 exists for: calendar_query chained into
-- travel_directions, ending on the iteration cap so the termination badge has
-- something to say.
--
-- Two details that are easy to get wrong and would make this misbehave:
--
--   * The message carries `user_id`. `messages_owner` RLS is
--     `auth.uid() = user_id`, so without it the browser cannot read the prompt
--     back and every trace card would read "(message cleared)".
--   * The exchange is inserted already claimed, and with its assistant reply.
--     An unclaimed user message is work: the worker would answer this question
--     for real the moment it starts. The stale-claim reaper leaves a claim
--     alone once an assistant reply exists after `claimed_at`.

BEGIN;

DO $$
DECLARE
  v_user    UUID;
  v_message UUID;
  v_run     UUID := gen_random_uuid();
  v_t       TIMESTAMPTZ := NOW() - INTERVAL '3 minutes';
  v_answer  TEXT := E'Tomorrow: standup at 09:30 (Zoom), design review 11:00–12:00 at 12 Bridge St, and a 1:1 with Priya at 15:00.\n\nLeave by **10:15** for the design review — 38 minutes on transit, arriving 10:53.';
BEGIN
  -- Whoever actually chats here, rather than whoever signed up first.
  SELECT user_id INTO v_user
    FROM public.messages
   WHERE user_id IS NOT NULL
   GROUP BY user_id
   ORDER BY count(*) DESC
   LIMIT 1;

  IF v_user IS NULL THEN
    SELECT id INTO v_user FROM auth.users LIMIT 1;
  END IF;

  IF v_user IS NULL THEN
    RAISE EXCEPTION 'No users found — nothing to attribute the run to.';
  END IF;

  INSERT INTO public.messages (role, content, model_used, user_id, claimed_by, claimed_at, created_at)
  VALUES ('user', 'What''s on tomorrow and when do I need to leave?', 'user',
          v_user, 'trace-seed', v_t + INTERVAL '1 second', v_t)
  RETURNING id INTO v_message;

  INSERT INTO public.messages (role, content, model_used, user_id, created_at)
  VALUES ('assistant', v_answer, 'gemini-2.5-flash', v_user, v_t + INTERVAL '21 seconds');

  INSERT INTO public.agent_turns
    (run_id, user_id, message_id, step_index, type, tool_name, args, result, error, model, latency_ms, created_at)
  VALUES
    (v_run, v_user, v_message, 0, 'thought', NULL, NULL,
     'Two things are being asked: what is scheduled tomorrow, and the travel time to the first thing with an address. Calendar first.',
     NULL, 'gemini-2.5-flash', NULL, v_t + INTERVAL '1 second'),

    (v_run, v_user, v_message, 0, 'tool_call', 'calendar_query',
     '{"start": "2026-09-02T00:00:00+10:00", "end": "2026-09-02T23:59:59+10:00"}'::jsonb,
     NULL, NULL, 'gemini-2.5-flash', NULL, v_t + INTERVAL '2 seconds'),

    (v_run, v_user, v_message, 0, 'tool_result', 'calendar_query',
     '{"start": "2026-09-02T00:00:00+10:00", "end": "2026-09-02T23:59:59+10:00"}'::jsonb,
     E'09:30–10:15  Standup (Zoom)\n11:00–12:00  Design review — 12 Bridge St, Sydney NSW 2000\n15:00–15:30  1:1 with Priya (Zoom)',
     NULL, 'gemini-2.5-flash', 412, v_t + INTERVAL '3 seconds'),

    (v_run, v_user, v_message, 1, 'thought', NULL, NULL,
     'The design review is the only one with an address. Travel time from home to 12 Bridge St, arriving by 11:00.',
     NULL, 'gemini-2.5-flash', NULL, v_t + INTERVAL '5 seconds'),

    (v_run, v_user, v_message, 1, 'tool_call', 'travel_directions',
     '{"destination": "12 Bridge St, Sydney NSW 2000", "arrive_by": "2026-09-02T11:00:00+10:00"}'::jsonb,
     NULL, NULL, 'gemini-2.5-flash', NULL, v_t + INTERVAL '6 seconds'),

    (v_run, v_user, v_message, 1, 'tool_result', 'travel_directions',
     '{"destination": "12 Bridge St, Sydney NSW 2000", "arrive_by": "2026-09-02T11:00:00+10:00"}'::jsonb,
     'Transit, 38 min door to door. Leave by 10:15 to arrive 10:53. Walk 8 min to the station, T1 at 10:26, walk 6 min the other end.',
     NULL, 'gemini-2.5-flash', 1180, v_t + INTERVAL '8 seconds'),

    -- A failing tool, because the traces worth reading are the ones that went wrong.
    (v_run, v_user, v_message, 2, 'tool_call', 'weather_forecast',
     '{"location": "Sydney", "date": "2026-09-02"}'::jsonb,
     NULL, NULL, 'gemini-2.5-flash', NULL, v_t + INTERVAL '10 seconds'),

    (v_run, v_user, v_message, 2, 'tool_result', 'weather_forecast',
     '{"location": "Sydney", "date": "2026-09-02"}'::jsonb,
     NULL, 'TimeoutError: no response from the forecast API after 10s',
     'gemini-2.5-flash', 10004, v_t + INTERVAL '20 seconds'),

    (v_run, v_user, v_message, 3, 'loop_break', NULL, NULL, NULL,
     'cap-hit', 'gemini-2.5-flash', NULL, v_t + INTERVAL '21 seconds'),

    -- The stored `final` keeps the "[capped]" note the user never sees in chat.
    (v_run, v_user, v_message, 3, 'final', NULL, NULL,
     v_answer || ' [capped]',
     NULL, 'gemini-2.5-flash', 21400, v_t + INTERVAL '21 seconds');

  RAISE NOTICE 'Seeded run % for user % (message %)', v_run, v_user, v_message;
END $$;

COMMIT;

-- ── Teardown ───────────────────────────────────────────────────────────────
-- Deletes the seeded exchange. agent_turns.message_id is ON DELETE CASCADE, so
-- the turns go with it. Safe to run twice.
--
--   DELETE FROM public.messages WHERE claimed_by = 'trace-seed';
--   DELETE FROM public.messages
--    WHERE role = 'assistant'
--      AND content LIKE 'Tomorrow: standup at 09:30%';
