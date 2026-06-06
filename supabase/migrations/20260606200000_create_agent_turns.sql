CREATE TABLE IF NOT EXISTS public.agent_turns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    message_id UUID REFERENCES public.messages(id) ON DELETE CASCADE,
    step_index INTEGER NOT NULL,
    type TEXT NOT NULL,
    tool_name TEXT,
    args JSONB,
    result JSONB,
    error TEXT,
    model TEXT,
    latency_ms INTEGER,
    est_tokens INTEGER,
    est_cost NUMERIC,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE public.agent_turns ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can manage their own agent turns"
    ON public.agent_turns
    FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);
