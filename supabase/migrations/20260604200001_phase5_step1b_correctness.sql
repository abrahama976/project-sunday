-- Migration: Phase 5 Step 1b Correctness
-- 1. Add `name` column to `user_profile`
ALTER TABLE user_profile ADD COLUMN IF NOT EXISTS name text;

-- 2. Create helper to get users for cron jobs (bypasses auth schema restrictions)
CREATE OR REPLACE FUNCTION get_active_users()
RETURNS TABLE(user_id uuid, email text, name text)
LANGUAGE plpgsql SECURITY DEFINER
AS $$
BEGIN
    RETURN QUERY
    SELECT 
        u.id,
        u.email::text,
        p.name
    FROM auth.users u
    LEFT JOIN public.user_profile p ON p.user_id = u.id;
END;
$$;

-- 3. Update increment_llm_usage with transactional locks and caps
CREATE OR REPLACE FUNCTION increment_llm_usage(
    p_user_id uuid,
    p_date date,
    p_model text,
    p_daily_cap integer,
    p_global_cap integer
)
RETURNS integer
LANGUAGE plpgsql
AS $$
DECLARE
    v_count integer;
    v_global_sum integer;
    v_lock_id bigint;
BEGIN
    -- Derive a lock ID from the model name and date
    -- hashtext returns integer, we cast to bigint to use in pg_advisory_xact_lock
    v_lock_id := hashtext('llm_budget_' || p_model || '_' || p_date::text)::bigint;

    -- Acquire transaction-level advisory lock to serialize requests for this model+date
    PERFORM pg_advisory_xact_lock(v_lock_id);

    -- 1. Check global cap
    SELECT COALESCE(SUM(request_count), 0) INTO v_global_sum
    FROM user_llm_ledger
    WHERE ledger_date = p_date AND model = p_model;

    IF v_global_sum >= p_global_cap THEN
        RETURN -1;
    END IF;

    -- 2. Atomic UPSERT enforcing per-user daily cap
    INSERT INTO user_llm_ledger (user_id, ledger_date, model, request_count)
    VALUES (p_user_id, p_date, p_model, 1)
    ON CONFLICT (user_id, ledger_date, model)
    DO UPDATE SET request_count = user_llm_ledger.request_count + 1
    WHERE user_llm_ledger.request_count < p_daily_cap
    RETURNING request_count INTO v_count;

    RETURN COALESCE(v_count, -1);
END;
$$;
