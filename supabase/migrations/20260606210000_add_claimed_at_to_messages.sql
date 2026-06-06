ALTER TABLE messages
  ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_messages_claimed_at
  ON messages (claimed_at)
  WHERE claimed_by IS NOT NULL;
