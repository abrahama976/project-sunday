ALTER TABLE scheduled_jobs
  ADD COLUMN IF NOT EXISTS last_executed_at TIMESTAMPTZ;
