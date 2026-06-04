INSERT INTO storage.buckets (id, name, public) 
VALUES ('cold_archive', 'cold_archive', false) 
ON CONFLICT (id) DO NOTHING;

-- RLS for the bucket
-- Since the Python worker will upload archives using the service role key, 
-- it bypasses RLS, but we can allow authenticated users to read their own archives if needed.
-- But since it's just the worker archiving it globally per user, we can keep it private.
CREATE POLICY "Allow authenticated users to read cold archive" 
ON storage.objects FOR SELECT 
TO authenticated 
USING (bucket_id = 'cold_archive' AND auth.uid()::text = (storage.foldername(name))[1]);
