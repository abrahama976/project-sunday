-- Type CHECK: loop will write exactly these five values
ALTER TABLE public.agent_turns
  ADD CONSTRAINT agent_turns_type_check
  CHECK (type IN (
    'thought',
    'tool_call', 
    'tool_result',
    'final',
    'loop_break'
  ));

-- run_id index: makes per-turn queries fast; also makes T2 a no-op
CREATE INDEX IF NOT EXISTS idx_agent_turns_run_id
  ON public.agent_turns (run_id);

-- user_id index: needed for dashboard/trace queries
CREATE INDEX IF NOT EXISTS idx_agent_turns_user_id
  ON public.agent_turns (user_id);

-- result column: change JSONB → TEXT
-- The loop writes truncated string output, not structured JSON.
-- Coerce existing rows (table is empty in prod) safely.
ALTER TABLE public.agent_turns
  ALTER COLUMN result TYPE TEXT USING result::text;
