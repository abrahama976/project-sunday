-- heartbeat.py has always upserted a `status` column that no migration ever
-- created. If the column was added by hand in the dashboard this is a no-op;
-- if it was not, every heartbeat write has been failing.
ALTER TABLE public.mac_heartbeat
  ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'offline';

-- The watchdog (see 20260828140000) reads last_seen on every run.
CREATE INDEX IF NOT EXISTS idx_mac_heartbeat_last_seen
  ON public.mac_heartbeat (last_seen);
