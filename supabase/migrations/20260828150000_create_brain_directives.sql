-- The learning brain: durable behavioural directives.
--
-- This is deliberately NOT the same store as user_profile. The two hold
-- different kinds of memory and they fail differently:
--
--   user_profile      facts about the user ("lives in Sydney"). A markdown
--                     blob is fine — facts are read, rarely revised.
--   brain_directives  rules about how to serve the user ("give code without
--                     comments"). These get contradicted, refined and retired,
--                     which a markdown blob cannot express — you cannot
--                     supersede a bullet inside a blob, or say where it came
--                     from, or turn one off without losing its history.
--
-- Directives are injected into the system prompt on every request, which makes
-- this table a self-modifying instruction set. Three constraints keep that
-- safe, and they are enforced in executors/brain_ops.py as well as here:
--   1. brain_learn is 'approve' tier — nothing lands without the user's tap.
--   2. source='tool' is rejected. A directive may only originate from
--      something the USER said, never from fetched web pages or tool output,
--      or web_fetch becomes a persistent prompt-injection vector.
--   3. Active directives are capped in both count and characters, so the
--      prompt cannot grow without bound against a 250 request/day budget.

CREATE TABLE IF NOT EXISTS public.brain_directives (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,

    -- The rule itself, phrased imperatively: "Answer with code first, prose after."
    directive         TEXT NOT NULL,

    -- Which situations it applies to. 'general' always applies; the rest are
    -- injected in full today, but the column lets the loop scope them later.
    scope             TEXT NOT NULL DEFAULT 'general',

    -- Provenance. 'user' = the user asked for this directly.
    -- 'inferred' = the summariser proposed it from observed behaviour.
    -- 'tool' is intentionally absent from the CHECK — see note 2 above.
    source            TEXT NOT NULL DEFAULT 'user',
    source_message_id UUID REFERENCES public.messages(id) ON DELETE SET NULL,

    -- When a new directive contradicts an old one we deactivate the old row
    -- and point at it, rather than editing in place. The history is the point:
    -- it is how you audit why the assistant behaves the way it does.
    supersedes        UUID REFERENCES public.brain_directives(id) ON DELETE SET NULL,

    active            BOOLEAN NOT NULL DEFAULT TRUE,

    -- 1..5. Ordering hint for prompt assembly and the first thing consulted
    -- when the cap forces a decision about what to drop.
    weight            SMALLINT NOT NULL DEFAULT 3,

    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT brain_directives_source_check
        CHECK (source IN ('user', 'inferred')),
    CONSTRAINT brain_directives_weight_check
        CHECK (weight BETWEEN 1 AND 5),
    -- A directive long enough to be a paragraph is a note, not a rule.
    CONSTRAINT brain_directives_length_check
        CHECK (char_length(directive) BETWEEN 3 AND 500),
    CONSTRAINT brain_directives_scope_check
        CHECK (scope IN ('general', 'code', 'calendar', 'email', 'tasks', 'news', 'health', 'travel'))
);

-- The hot path: every system prompt build reads the active set for one user.
CREATE INDEX IF NOT EXISTS idx_brain_directives_active
    ON public.brain_directives (user_id, active, weight DESC);

CREATE INDEX IF NOT EXISTS idx_brain_directives_user
    ON public.brain_directives (user_id);

-- Case-insensitive duplicate guard. The executor also does fuzzy matching, but
-- this stops the exact-repeat case at the database regardless of code path.
CREATE UNIQUE INDEX IF NOT EXISTS idx_brain_directives_unique_active
    ON public.brain_directives (user_id, lower(directive))
    WHERE active;

ALTER TABLE public.brain_directives ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can manage their own brain directives"
    ON public.brain_directives
    FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

CREATE OR REPLACE FUNCTION public.touch_brain_directives_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = ''
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_brain_directives_updated_at ON public.brain_directives;
CREATE TRIGGER trg_brain_directives_updated_at
    BEFORE UPDATE ON public.brain_directives
    FOR EACH ROW
    EXECUTE FUNCTION public.touch_brain_directives_updated_at();
