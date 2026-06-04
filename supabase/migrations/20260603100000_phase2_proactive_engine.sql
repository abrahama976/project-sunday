-- =============================================================================
-- Project Sunday — Phase 2: Proactive Life Engine
-- Date: 2026-06-03
-- =============================================================================
-- Alters:  tasks (add tags, flexibility_score, is_archived)
--          health_logs (add meal_type, description, water_ml)
-- Creates: user_location, message_summaries
-- Seeds:   3 new scheduled jobs
-- =============================================================================


-- =============================================================================
-- 1. ALTER tasks — add new columns
-- =============================================================================
alter table public.tasks
  add column if not exists tags text[] default '{}',
  add column if not exists flexibility_score smallint not null default 3,
  add column if not exists is_archived boolean not null default false;

-- Constraints
alter table public.tasks
  add constraint tasks_flexibility_range check (flexibility_score between 1 and 5);

-- Indexes
create index if not exists tasks_is_archived_idx on public.tasks (is_archived) where is_archived = false;
create index if not exists tasks_tags_idx on public.tasks using gin (tags);


-- =============================================================================
-- 2. ALTER health_logs — add meal tracking columns
-- =============================================================================

-- Relax the metric constraint to allow meal-type entries
alter table public.health_logs
  drop constraint if exists health_logs_metric_check;

alter table public.health_logs
  add constraint health_logs_metric_check
    check (metric in ('steps', 'sleep_hours', 'active_cal', 'weight', 'water_ml', 'meal', 'water'));

-- Add new columns
alter table public.health_logs
  add column if not exists meal_type text,
  add column if not exists description text,
  add column if not exists water_ml integer;

-- Constraint on meal_type
alter table public.health_logs
  add constraint health_logs_meal_type_check
    check (meal_type is null or meal_type in ('breakfast', 'lunch', 'dinner', 'snack'));

-- Drop the old unique constraint that doesn't account for meals
alter table public.health_logs
  drop constraint if exists health_logs_user_date_metric_unique;

-- Re-add a unique constraint that also includes meal_type (null-safe via COALESCE)
create unique index if not exists health_logs_user_date_metric_meal_unique
  on public.health_logs (user_id, log_date, metric, coalesce(meal_type, '__none__'));


-- =============================================================================
-- 3. CREATE user_location — user geolocation for timezone-aware scheduling
-- =============================================================================
create table if not exists public.user_location (
  id          uuid        primary key default gen_random_uuid(),
  user_id     uuid        references auth.users(id) on delete set null,
  lat         double precision not null,
  lng         double precision not null,
  timezone    text        not null default 'Australia/Sydney',
  updated_at  timestamptz not null default now()
);

-- Trigger
drop trigger if exists user_location_set_updated_at on public.user_location;
create trigger user_location_set_updated_at
  before update on public.user_location
  for each row execute function public.set_updated_at();

-- Index
create index if not exists user_location_user_id_idx on public.user_location (user_id);

-- RLS
alter table public.user_location enable row level security;
create policy authenticated_all_user_location on public.user_location
  for all to authenticated using (auth.uid() is not null) with check (auth.uid() is not null);


-- =============================================================================
-- 4. CREATE message_summaries — compressed conversation memory
-- =============================================================================
create table if not exists public.message_summaries (
  id            uuid        primary key default gen_random_uuid(),
  user_id       uuid        references auth.users(id) on delete set null,
  summary       text        not null,
  message_count integer     not null,
  date_from     timestamptz not null,
  date_to       timestamptz not null,
  created_at    timestamptz not null default now()
);

-- RLS
alter table public.message_summaries enable row level security;
create policy authenticated_all_message_summaries on public.message_summaries
  for all to authenticated using (auth.uid() is not null) with check (auth.uid() is not null);

-- Index
create index if not exists message_summaries_date_range_idx
  on public.message_summaries (date_from, date_to);


-- =============================================================================
-- 5. Add soft-delete column to messages
-- =============================================================================
alter table public.messages
  add column if not exists is_deleted boolean not null default false;

create index if not exists messages_is_deleted_idx on public.messages (is_deleted) where is_deleted = false;


-- =============================================================================
-- 6. SEED new scheduled jobs
-- =============================================================================
insert into public.scheduled_jobs (job_name, cron_expr, timezone, config) values
  ('meal_checkin',       '0 13,19 * * *', 'UTC',              '{"description": "Proactive meal check-in during free calendar windows"}'::jsonb),
  ('nightly_maintenance','0 3 * * *',     'Australia/Sydney',  '{"description": "Archive old tasks, compress messages, clean health_logs"}'::jsonb),
  ('calendar_prep',      '0 8 * * *',     'Australia/Sydney',  '{"description": "Generate prep tasks and travel estimates for today events"}'::jsonb)
on conflict (job_name) do nothing;


-- =============================================================================
-- 7. REALTIME — add new tables
-- =============================================================================
do $$
begin
  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime' and tablename = 'user_location'
  ) then
    alter publication supabase_realtime add table public.user_location;
  end if;
  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime' and tablename = 'message_summaries'
  ) then
    alter publication supabase_realtime add table public.message_summaries;
  end if;
end$$;
