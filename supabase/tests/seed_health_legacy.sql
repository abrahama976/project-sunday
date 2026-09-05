-- health_logs exactly as it stood before the fix, plus the rows production had
-- actually accumulated in it.
--
-- The DDL below is copied verbatim from the two migrations that built it —
-- 20260603000000 (phase 1) creates the table, 20260603100000 (phase 2) adds the
-- meal columns and replaces the unique constraint with the COALESCE expression
-- INDEX. Those files are not replayed directly because phase 1 also alters
-- `inventory`, which phase 3 dropped, so it can no longer run start to finish
-- against a current schema. The health_logs portion is reproduced here instead;
-- if either migration is ever edited, this must move with it.
--
-- The rows mirror the live table: two water taps on one day that have to merge
-- into a single 500 ml row, one meal per type, and a row on another day that
-- must come through untouched. NULL user_id throughout — which is precisely why
-- the unique index never fired, NULLs being distinct under it.

-- ── phase 1: the table ───────────────────────────────────────────────────────
create table if not exists public.health_logs (
  id        uuid          primary key default gen_random_uuid(),
  user_id   uuid          references auth.users(id) on delete set null,
  log_date  date          not null,
  metric    text          not null,
  value     numeric(10,2) not null,
  source    text          not null default 'manual',
  created_at timestamptz  not null default now(),

  constraint health_logs_user_date_metric_unique unique (user_id, log_date, metric),
  constraint health_logs_metric_check check (metric in ('steps', 'sleep_hours', 'active_cal', 'weight', 'water_ml')),
  constraint health_logs_source_check check (source in ('manual', 'shortcut', 'csv'))
);

create index if not exists health_logs_user_id_idx  on public.health_logs (user_id);
create index if not exists health_logs_log_date_idx on public.health_logs (log_date);
create index if not exists health_logs_metric_idx   on public.health_logs (metric);

-- ── phase 2: meals, and the expression index the client could not name ───────
alter table public.health_logs
  drop constraint if exists health_logs_metric_check;

alter table public.health_logs
  add constraint health_logs_metric_check
    check (metric in ('steps', 'sleep_hours', 'active_cal', 'weight', 'water_ml', 'meal', 'water'));

alter table public.health_logs
  add column if not exists meal_type text,
  add column if not exists description text,
  add column if not exists water_ml integer;

alter table public.health_logs
  add constraint health_logs_meal_type_check
    check (meal_type is null or meal_type in ('breakfast', 'lunch', 'dinner', 'snack'));

alter table public.health_logs
  drop constraint if exists health_logs_user_date_metric_unique;

create unique index if not exists health_logs_user_date_metric_meal_unique
  on public.health_logs (user_id, log_date, metric, coalesce(meal_type, '__none__'));

-- ── the rows that accumulated while that index was inert ─────────────────────
INSERT INTO auth.users (id) VALUES ('c0ffee00-0000-4000-8000-000000000001')
ON CONFLICT DO NOTHING;

INSERT INTO public.user_profile (user_id)
VALUES ('c0ffee00-0000-4000-8000-000000000001')
ON CONFLICT DO NOTHING;

INSERT INTO public.health_logs
    (user_id, log_date, metric, value, meal_type, source, created_at)
VALUES
    -- Two taps of "+250 ml" on the same day. These must become one 500 ml row.
    (NULL, DATE '2026-06-09', 'water', 250, NULL, 'manual', '2026-06-09 02:01:28+00'),
    (NULL, DATE '2026-06-09', 'water', 250, NULL, 'manual', '2026-06-09 02:01:30+00'),
    -- Same day, different metric: must survive as its own row.
    (NULL, DATE '2026-06-09', 'meal',    0, 'breakfast', 'manual', '2026-06-09 02:01:26+00'),
    -- Same day, same metric, different meal type: also its own row. This is the
    -- case the COALESCE in the old index existed for.
    (NULL, DATE '2026-06-09', 'meal',    0, 'lunch',     'manual', '2026-06-09 05:00:00+00'),
    -- A different day entirely.
    (NULL, DATE '2026-06-06', 'water', 250, NULL, 'manual', '2026-06-06 05:09:23+00');
