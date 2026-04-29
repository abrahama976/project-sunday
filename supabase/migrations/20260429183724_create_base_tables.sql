-- ============================================
-- PROJECT SUNDAY — BASE TABLES
-- ============================================

-- 1. CHAT HISTORY
-- Stores every message exchanged with the AI
CREATE TABLE IF NOT EXISTS messages (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  role        TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
  content     TEXT NOT NULL,
  model_used  TEXT,
  session_id  uuid,
  created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- 2. ACTION QUEUE (Human-in-the-Loop core)
-- AI proposes actions here. Mac worker only executes after approved = TRUE
CREATE TABLE IF NOT EXISTS action_queue (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  action_type  TEXT NOT NULL,
  payload      JSONB NOT NULL,
  status       TEXT DEFAULT 'pending' CHECK (status IN ('pending','approved','denied','executed','failed')),
  approved     BOOLEAN,
  created_at   TIMESTAMPTZ DEFAULT NOW(),
  executed_at  TIMESTAMPTZ
);

-- 3. MAC HEARTBEAT
-- Mac worker updates this every 60 seconds so the system knows if Mac is online
CREATE TABLE IF NOT EXISTS mac_heartbeat (
  id          INT PRIMARY KEY DEFAULT 1,
  last_seen   TIMESTAMPTZ DEFAULT NOW(),
  mac_name    TEXT DEFAULT 'MacBook Pro'
);
INSERT INTO mac_heartbeat (id) VALUES (1) ON CONFLICT DO NOTHING;

-- 4. FOOD INVENTORY
-- For meal planning cross-referenced against calendar
CREATE TABLE IF NOT EXISTS inventory (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  item         TEXT NOT NULL,
  quantity     FLOAT NOT NULL DEFAULT 1,
  unit         TEXT,
  expiry_date  DATE,
  category     TEXT,
  created_at   TIMESTAMPTZ DEFAULT NOW(),
  updated_at   TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================
-- ROW LEVEL SECURITY
-- ============================================
ALTER TABLE messages       ENABLE ROW LEVEL SECURITY;
ALTER TABLE action_queue   ENABLE ROW LEVEL SECURITY;
ALTER TABLE mac_heartbeat  ENABLE ROW LEVEL SECURITY;
ALTER TABLE inventory      ENABLE ROW LEVEL SECURITY;

-- Service role bypass (for FastAPI worker)
CREATE POLICY "Service role full access - messages"
  ON messages FOR ALL USING (true);

CREATE POLICY "Service role full access - action_queue"
  ON action_queue FOR ALL USING (true);

CREATE POLICY "Service role full access - mac_heartbeat"
  ON mac_heartbeat FOR ALL USING (true);

CREATE POLICY "Service role full access - inventory"
  ON inventory FOR ALL USING (true);

-- ============================================
-- REALTIME — enable on action_queue
-- So PWA instantly sees new approval requests
-- ============================================
ALTER PUBLICATION supabase_realtime ADD TABLE action_queue;
ALTER PUBLICATION supabase_realtime ADD TABLE mac_heartbeat;