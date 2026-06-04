DROP POLICY IF EXISTS tasks_open ON tasks;
DROP POLICY IF EXISTS authenticated_all_tasks ON tasks;
CREATE POLICY tasks_owner ON tasks
  FOR ALL TO authenticated
  USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);
