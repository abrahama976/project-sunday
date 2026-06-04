-- Drop the permissive catch-all policy
DROP POLICY IF EXISTS authenticated_all_messages ON messages;
-- Users can only read/write their own messages
CREATE POLICY messages_owner ON messages
  FOR ALL
  TO authenticated
  USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);
