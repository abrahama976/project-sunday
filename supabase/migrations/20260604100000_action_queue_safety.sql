-- Migration: Action Queue Safety — add 'awaiting_approval' status
-- This fixes the race condition where the worker could claim unapproved rows.

-- 1. Expand the status CHECK constraint to include 'awaiting_approval'
ALTER TABLE action_queue DROP CONSTRAINT IF EXISTS action_queue_status_check;
ALTER TABLE action_queue ADD CONSTRAINT action_queue_status_check 
    CHECK (status IN ('pending', 'awaiting_approval', 'approved', 'denied', 'processing', 'executed', 'failed', 'expired'));

-- 2. Migrate existing unapproved 'pending' rows (tier != 'auto' AND approved IS NULL)
--    to the new 'awaiting_approval' status.
UPDATE action_queue 
SET status = 'awaiting_approval' 
WHERE status = 'pending' AND tier != 'auto' AND approved IS NULL;
