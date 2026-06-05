-- Claim lock: prevents race condition between Mac worker and future cloud brain
ALTER TABLE public.messages ADD COLUMN IF NOT EXISTS claimed_by text DEFAULT NULL;
CREATE INDEX IF NOT EXISTS idx_messages_claimed_by ON public.messages(claimed_by) WHERE claimed_by IS NULL;
