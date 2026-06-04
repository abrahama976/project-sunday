-- Migration: Formal LLM Budget Gate (Phase 5, Step 1)
-- UP: Add 'model' column, new unique constraint, request_count column,
--      and atomic increment function.

-- 1. Add new columns
ALTER TABLE user_llm_ledger ADD COLUMN IF NOT EXISTS model text NOT NULL DEFAULT 'flash';
ALTER TABLE user_llm_ledger ADD COLUMN IF NOT EXISTS request_count integer NOT NULL DEFAULT 0;

-- 2. Backfill: copy flash_requests into request_count for existing rows
UPDATE user_llm_ledger SET request_count = flash_requests WHERE model = 'flash' AND request_count = 0 AND flash_requests > 0;

-- 3. Replace the unique constraint
ALTER TABLE user_llm_ledger DROP CONSTRAINT IF EXISTS user_llm_ledger_user_id_ledger_date_key;
ALTER TABLE user_llm_ledger ADD CONSTRAINT user_llm_ledger_user_date_model_key
    UNIQUE (user_id, ledger_date, model);

-- 4. Atomic increment function (INSERT ... ON CONFLICT DO UPDATE RETURNING)
CREATE OR REPLACE FUNCTION increment_llm_usage(
    p_user_id uuid,
    p_date date,
    p_model text
)
RETURNS integer
LANGUAGE plpgsql
AS $$
DECLARE
    v_count integer;
BEGIN
    INSERT INTO user_llm_ledger (user_id, ledger_date, model, request_count)
    VALUES (p_user_id, p_date, p_model, 1)
    ON CONFLICT (user_id, ledger_date, model)
    DO UPDATE SET request_count = user_llm_ledger.request_count + 1
    RETURNING request_count INTO v_count;

    RETURN v_count;
END;
$$;

-- 5. Read-only function to check current usage without incrementing
CREATE OR REPLACE FUNCTION get_llm_usage(
    p_user_id uuid,
    p_date date,
    p_model text
)
RETURNS integer
LANGUAGE plpgsql
AS $$
DECLARE
    v_count integer;
BEGIN
    SELECT request_count INTO v_count
    FROM user_llm_ledger
    WHERE user_id = p_user_id AND ledger_date = p_date AND model = p_model;

    RETURN COALESCE(v_count, 0);
END;
$$;
