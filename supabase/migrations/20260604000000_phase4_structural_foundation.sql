-- Migration: Phase 4 Structural Foundation (Tenancy, Budgeting, Canonical Data, Queue Lifecycle)

-- 1. Budgeting Ledger
CREATE TABLE IF NOT EXISTS user_llm_ledger (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid REFERENCES auth.users(id) ON DELETE CASCADE,
    ledger_date date NOT NULL DEFAULT CURRENT_DATE,
    flash_requests integer NOT NULL DEFAULT 0,
    lite_requests integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, ledger_date)
);

ALTER TABLE user_llm_ledger ENABLE ROW LEVEL SECURITY;
CREATE POLICY authenticated_user_llm_ledger ON user_llm_ledger 
    FOR ALL TO authenticated 
    USING (auth.uid() = user_id) 
    WITH CHECK (auth.uid() = user_id);

-- 2. Tasks Cooldown
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS last_nudged_at timestamptz;

-- 3. Canonical Health Logs
-- Move existing water_ml data to standard value column if necessary
UPDATE health_logs 
SET metric = 'water', value = COALESCE(water_ml, 0) 
WHERE metric = 'water_ml' OR water_ml IS NOT NULL;

ALTER TABLE health_logs DROP COLUMN IF EXISTS water_ml;

-- 4. Tenancy Scoping
ALTER TABLE messages ADD COLUMN IF NOT EXISTS user_id uuid REFERENCES auth.users(id) ON DELETE CASCADE;
ALTER TABLE action_queue ADD COLUMN IF NOT EXISTS user_id uuid REFERENCES auth.users(id) ON DELETE CASCADE;

-- 5. Action Queue Lifecycle
ALTER TABLE action_queue ADD COLUMN IF NOT EXISTS failed_reason text;

ALTER TABLE action_queue DROP CONSTRAINT IF EXISTS action_queue_status_check;
ALTER TABLE action_queue ADD CONSTRAINT action_queue_status_check 
    CHECK (status in ('pending', 'approved', 'denied', 'processing', 'executed', 'failed', 'expired'));

