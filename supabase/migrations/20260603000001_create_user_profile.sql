CREATE TABLE user_profile (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id uuid REFERENCES auth.users(id) UNIQUE NOT NULL,
    content text NOT NULL DEFAULT '',
    updated_at timestamptz DEFAULT now()
);

ALTER TABLE user_profile ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can manage their own profile" 
ON user_profile FOR ALL 
TO authenticated 
USING (auth.uid() = user_id) 
WITH CHECK (auth.uid() = user_id);

CREATE TRIGGER set_updated_at
BEFORE UPDATE ON user_profile
FOR EACH ROW
EXECUTE FUNCTION public.set_updated_at();
