-- Minimal stand-ins so the real migrations can be executed on a bare Postgres:
-- the Supabase-managed pieces (auth schema, pg_cron, pg_net) plus the two
-- tables the new migrations touch.

-- Supabase ships these roles; a bare postgres does not. RLS policies written
-- `TO authenticated` fail to create without it, which is a migration that
-- would deploy fine and only break here.
DO $stub$ BEGIN
    CREATE ROLE authenticated;
EXCEPTION WHEN duplicate_object THEN NULL;
END $stub$;
DO $stub$ BEGIN
    CREATE ROLE anon;
EXCEPTION WHEN duplicate_object THEN NULL;
END $stub$;

CREATE SCHEMA IF NOT EXISTS auth;
CREATE SCHEMA IF NOT EXISTS net;
CREATE SCHEMA IF NOT EXISTS cron;
CREATE SCHEMA IF NOT EXISTS extensions;

CREATE TABLE IF NOT EXISTS auth.users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid()
);

CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid
LANGUAGE sql STABLE AS $$ SELECT NULL::uuid $$;

-- pg_net: the real signature we depend on.
CREATE OR REPLACE FUNCTION net.http_post(
    url text,
    body jsonb DEFAULT '{}'::jsonb,
    params jsonb DEFAULT '{}'::jsonb,
    headers jsonb DEFAULT '{}'::jsonb,
    timeout_milliseconds int DEFAULT 5000
) RETURNS bigint
LANGUAGE sql AS $$ SELECT 1::bigint $$;

-- pg_cron.
-- Column set mirrors real pg_cron, including `active` — the runbook's
-- verification query selects it, so a stub without it would pass here and
-- fail against a real database.
CREATE TABLE IF NOT EXISTS cron.job (
    jobid bigserial PRIMARY KEY,
    jobname text,
    schedule text,
    command text,
    nodename text DEFAULT 'localhost',
    nodeport int DEFAULT 5432,
    database text DEFAULT 'postgres',
    username text DEFAULT 'postgres',
    active boolean DEFAULT true
);

CREATE OR REPLACE FUNCTION cron.schedule(job_name text, schedule text, command text)
RETURNS bigint LANGUAGE sql AS $$
    INSERT INTO cron.job (jobname, schedule, command)
    VALUES (job_name, schedule, command) RETURNING jobid;
$$;

CREATE OR REPLACE FUNCTION cron.unschedule(job_name text)
RETURNS boolean LANGUAGE sql AS $$
    DELETE FROM cron.job WHERE jobname = job_name; SELECT true;
$$;

-- Tables the new migrations reference.
CREATE TABLE IF NOT EXISTS public.mac_heartbeat (
    id        INT PRIMARY KEY DEFAULT 1,
    last_seen TIMESTAMPTZ DEFAULT NOW(),
    mac_name  TEXT DEFAULT 'MacBook Pro'
);
INSERT INTO public.mac_heartbeat (id) VALUES (1) ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS public.messages (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid()
);

CREATE TABLE IF NOT EXISTS public.scheduled_jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_name  text UNIQUE NOT NULL,
    cron_expr text NOT NULL,
    timezone  text DEFAULT 'UTC',
    -- Present in the real table, and migrations that register a job write to
    -- both. Without them the travel migrations fail here and nowhere else.
    enabled   boolean NOT NULL DEFAULT true,
    config    jsonb
);
INSERT INTO public.scheduled_jobs (job_name, cron_expr, timezone) VALUES
    ('meal_checkin',         '0 13,19 * * *', 'UTC'),
    ('daily_brief',          '0 22 * * *',    'UTC'),
    ('cold_storage_archive', '0 3 * * 0',     'UTC')
ON CONFLICT (job_name) DO NOTHING;
