  CREATE TABLE IF NOT EXISTS one_off_reminders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    remind_at TIMESTAMPTZ NOT NULL,
    message TEXT NOT NULL,
    fired BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
  );

  ALTER TABLE one_off_reminders ENABLE ROW LEVEL SECURITY;

  CREATE POLICY "Users manage own reminders"
    ON one_off_reminders FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

  CREATE INDEX IF NOT EXISTS idx_one_off_reminders_unfired
    ON one_off_reminders (user_id, remind_at)
    WHERE fired = FALSE;
