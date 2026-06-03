-- =============================================================================
-- Project Sunday — Phase 1 Foundation Tables
-- Date: 2026-06-03
-- =============================================================================
-- Creates: tasks, daily_briefings, news_items, travel_routes, scheduled_jobs,
--          expenses, health_logs
-- Alters:  messages (add metadata), inventory (add user_id)
-- Seeds:   default scheduled_jobs entries
-- =============================================================================


-- =============================================================================
-- 1. ALTER EXISTING TABLES
-- =============================================================================

-- 1a. Add metadata jsonb column to messages
alter table public.messages
  add column if not exists metadata jsonb;

-- 1b. Add user_id to inventory for multi-user prep
alter table public.inventory
  add column if not exists user_id uuid references auth.users(id) on delete set null;

-- Index for inventory user_id lookups
create index if not exists inventory_user_id_idx on public.inventory (user_id);


-- =============================================================================
-- 2. TASKS — Personal task management
-- =============================================================================
create table if not exists public.tasks (
  id                uuid        primary key default gen_random_uuid(),
  user_id           uuid        references auth.users(id) on delete set null,
  title             text        not null,
  description       text,
  category          text,                                       -- 'work', 'personal', 'health', 'finance', 'project'
  priority          smallint    not null default 3,              -- 1=urgent … 5=someday
  status            text        not null default 'open',
  due_date          date,
  due_time          time,
  recurrence        text,                                       -- null, 'daily', 'weekly', 'monthly'
  source            text,                                       -- 'chat', 'briefing', 'manual'
  source_message_id uuid        references public.messages(id) on delete set null,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  completed_at      timestamptz,

  constraint tasks_priority_range   check (priority between 1 and 5),
  constraint tasks_status_check     check (status in ('open', 'in_progress', 'done', 'cancelled')),
  constraint tasks_recurrence_check check (recurrence is null or recurrence in ('daily', 'weekly', 'monthly')),
  constraint tasks_source_check     check (source is null or source in ('chat', 'briefing', 'manual'))
);

-- Indexes
create index if not exists tasks_user_id_idx      on public.tasks (user_id);
create index if not exists tasks_status_idx        on public.tasks (status);
create index if not exists tasks_due_date_idx      on public.tasks (due_date) where due_date is not null;
create index if not exists tasks_category_idx      on public.tasks (category) where category is not null;
create index if not exists tasks_priority_idx      on public.tasks (priority, status);

-- Trigger
drop trigger if exists tasks_set_updated_at on public.tasks;
create trigger tasks_set_updated_at
  before update on public.tasks
  for each row execute function public.set_updated_at();


-- =============================================================================
-- 3. DAILY BRIEFINGS — Morning briefing content
-- =============================================================================
create table if not exists public.daily_briefings (
  id             uuid        primary key default gen_random_uuid(),
  user_id        uuid        references auth.users(id) on delete set null,
  briefing_date  date        not null,
  content        text        not null,                          -- rendered markdown
  sections       jsonb,                                         -- {schedule:[], emails:[], news:[], tasks:[]}
  generated_at   timestamptz not null default now(),

  constraint daily_briefings_user_date_unique unique (user_id, briefing_date)
);

-- Indexes
create index if not exists daily_briefings_user_id_idx       on public.daily_briefings (user_id);
create index if not exists daily_briefings_briefing_date_idx on public.daily_briefings (briefing_date);


-- =============================================================================
-- 4. NEWS ITEMS — Cached news articles
-- =============================================================================
create table if not exists public.news_items (
  id           uuid        primary key default gen_random_uuid(),
  user_id      uuid        references auth.users(id) on delete set null,
  title        text        not null,
  source       text,                                            -- feed name
  url          text,
  summary      text,                                            -- AI-generated
  relevance    real,                                             -- 0.0–1.0
  category     text,                                            -- 'tech', 'finance', 'local', 'startup'
  published_at timestamptz,
  fetched_at   timestamptz not null default now(),
  surfaced     boolean     not null default false,

  constraint news_items_relevance_range check (relevance is null or (relevance >= 0.0 and relevance <= 1.0)),
  constraint news_items_category_check  check (category is null or category in ('tech', 'finance', 'local', 'startup'))
);

-- Indexes
create index if not exists news_items_user_id_idx      on public.news_items (user_id);
create index if not exists news_items_surfaced_idx     on public.news_items (surfaced) where surfaced = false;
create index if not exists news_items_category_idx     on public.news_items (category) where category is not null;
create index if not exists news_items_published_at_idx on public.news_items (published_at desc);


-- =============================================================================
-- 5. TRAVEL ROUTES — Cached route queries
-- =============================================================================
create table if not exists public.travel_routes (
  id            uuid        primary key default gen_random_uuid(),
  user_id       uuid        references auth.users(id) on delete set null,
  origin        text        not null,
  destination   text        not null,
  mode          text        not null default 'transit',
  departure_at  timestamptz,
  arrival_at    timestamptz,
  duration_mins integer,
  route_data    jsonb,
  created_at    timestamptz not null default now(),

  constraint travel_routes_mode_check check (mode in ('transit', 'driving', 'walking'))
);

-- Indexes
create index if not exists travel_routes_user_id_idx    on public.travel_routes (user_id);
create index if not exists travel_routes_created_at_idx on public.travel_routes (created_at desc);


-- =============================================================================
-- 6. SCHEDULED JOBS — Worker job registry
-- =============================================================================
create table if not exists public.scheduled_jobs (
  id          uuid        primary key default gen_random_uuid(),
  job_name    text        not null,
  cron_expr   text        not null,                             -- e.g. '0 7 * * *'
  timezone    text        not null default 'Australia/Sydney',
  enabled     boolean     not null default true,
  last_run_at timestamptz,
  next_run_at timestamptz,
  config      jsonb,
  created_at  timestamptz not null default now(),

  constraint scheduled_jobs_job_name_unique unique (job_name)
);

-- Indexes
create index if not exists scheduled_jobs_enabled_idx on public.scheduled_jobs (enabled) where enabled = true;


-- =============================================================================
-- 7. EXPENSES — Phase 2 expense tracking (forward-compat stub)
-- =============================================================================
create table if not exists public.expenses (
  id                uuid          primary key default gen_random_uuid(),
  user_id           uuid          references auth.users(id) on delete set null,
  amount            numeric(12,2) not null,
  currency          text          not null default 'AUD',
  category          text,
  description       text,
  date              date          not null default current_date,
  source            text          not null default 'manual',
  source_message_id uuid          references public.messages(id) on delete set null,
  created_at        timestamptz   not null default now(),

  constraint expenses_source_check check (source in ('manual', 'csv_import', 'chat')),
  constraint expenses_amount_positive check (amount >= 0)
);

-- Indexes
create index if not exists expenses_user_id_idx  on public.expenses (user_id);
create index if not exists expenses_date_idx     on public.expenses (date);
create index if not exists expenses_category_idx on public.expenses (category) where category is not null;


-- =============================================================================
-- 8. HEALTH LOGS — Phase 2 health tracking (forward-compat stub)
-- =============================================================================
create table if not exists public.health_logs (
  id        uuid          primary key default gen_random_uuid(),
  user_id   uuid          references auth.users(id) on delete set null,
  log_date  date          not null,
  metric    text          not null,                              -- 'steps', 'sleep_hours', 'active_cal', 'weight', 'water_ml'
  value     numeric(10,2) not null,
  source    text          not null default 'manual',
  created_at timestamptz  not null default now(),

  constraint health_logs_user_date_metric_unique unique (user_id, log_date, metric),
  constraint health_logs_metric_check check (metric in ('steps', 'sleep_hours', 'active_cal', 'weight', 'water_ml')),
  constraint health_logs_source_check check (source in ('manual', 'shortcut', 'csv'))
);

-- Indexes
create index if not exists health_logs_user_id_idx  on public.health_logs (user_id);
create index if not exists health_logs_log_date_idx on public.health_logs (log_date);
create index if not exists health_logs_metric_idx   on public.health_logs (metric);


-- =============================================================================
-- 9. ROW LEVEL SECURITY
-- =============================================================================
alter table public.tasks           enable row level security;
alter table public.daily_briefings enable row level security;
alter table public.news_items      enable row level security;
alter table public.travel_routes   enable row level security;
alter table public.scheduled_jobs  enable row level security;
alter table public.expenses        enable row level security;
alter table public.health_logs     enable row level security;

-- Authenticated-only policies (single-user system: any logged-in user = you)
create policy authenticated_all_tasks on public.tasks
  for all to authenticated using (auth.uid() is not null) with check (auth.uid() is not null);

create policy authenticated_all_daily_briefings on public.daily_briefings
  for all to authenticated using (auth.uid() is not null) with check (auth.uid() is not null);

create policy authenticated_all_news_items on public.news_items
  for all to authenticated using (auth.uid() is not null) with check (auth.uid() is not null);

create policy authenticated_all_travel_routes on public.travel_routes
  for all to authenticated using (auth.uid() is not null) with check (auth.uid() is not null);

create policy authenticated_all_scheduled_jobs on public.scheduled_jobs
  for all to authenticated using (auth.uid() is not null) with check (auth.uid() is not null);

create policy authenticated_all_expenses on public.expenses
  for all to authenticated using (auth.uid() is not null) with check (auth.uid() is not null);

create policy authenticated_all_health_logs on public.health_logs
  for all to authenticated using (auth.uid() is not null) with check (auth.uid() is not null);


-- =============================================================================
-- 10. SEED DEFAULT SCHEDULED JOBS
-- =============================================================================
insert into public.scheduled_jobs (job_name, cron_expr, config) values
  ('morning_briefing', '0 7 * * *',     '{"description": "Generate and deliver the morning briefing"}'::jsonb),
  ('news_fetch',       '0 6,18 * * *',  '{"description": "Fetch and score news articles from configured feeds"}'::jsonb),
  ('email_scan',       '*/30 * * * *',   '{"description": "Scan inbox for actionable emails and surface summaries"}'::jsonb)
on conflict (job_name) do nothing;


-- =============================================================================
-- 11. REALTIME — publish new tables that the PWA should subscribe to
-- =============================================================================
do $$
begin
  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime' and tablename = 'tasks'
  ) then
    alter publication supabase_realtime add table public.tasks;
  end if;
  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime' and tablename = 'daily_briefings'
  ) then
    alter publication supabase_realtime add table public.daily_briefings;
  end if;
end$$;

-- Full-row replica identity for realtime UPDATE events
alter table public.tasks           replica identity full;
alter table public.daily_briefings replica identity full;
