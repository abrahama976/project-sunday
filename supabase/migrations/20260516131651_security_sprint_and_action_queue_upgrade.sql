-- =============================================================================
-- Project Sunday — Security Sprint + action_queue Upgrade
-- Date: 2026-05-16
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. updated_at trigger helper (used by multiple tables)
-- -----------------------------------------------------------------------------
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- -----------------------------------------------------------------------------
-- 2. Upgrade action_queue
-- -----------------------------------------------------------------------------

-- 2a. New columns
alter table public.action_queue
  add column if not exists idempotency_key uuid not null default gen_random_uuid(),
  add column if not exists error jsonb,
  add column if not exists tier text not null default 'approve',
  add column if not exists sequence_num bigint,
  add column if not exists depends_on uuid,
  add column if not exists updated_at timestamptz not null default now(),
  add column if not exists approved_at timestamptz,
  add column if not exists approved_by uuid;

-- 2b. Sequence for sequence_num (global ordering — simpler than per-conversation for now)
create sequence if not exists public.action_queue_seq;
alter table public.action_queue
  alter column sequence_num set default nextval('public.action_queue_seq');

-- Backfill any existing rows
update public.action_queue
  set sequence_num = nextval('public.action_queue_seq')
  where sequence_num is null;

alter table public.action_queue
  alter column sequence_num set not null;

-- 2c. Constraints
alter table public.action_queue
  add constraint action_queue_idempotency_key_unique unique (idempotency_key);

alter table public.action_queue
  drop constraint if exists action_queue_tier_check;
alter table public.action_queue
  add constraint action_queue_tier_check check (tier in ('auto', 'approve', 'hold'));

alter table public.action_queue
  drop constraint if exists action_queue_status_check;
alter table public.action_queue
  add constraint action_queue_status_check check (
    status in ('pending', 'approved', 'denied', 'executing', 'executed', 'failed', 'retrying')
  );

alter table public.action_queue
  add constraint action_queue_depends_on_fkey
    foreign key (depends_on) references public.action_queue(id) on delete set null;

alter table public.action_queue
  add constraint action_queue_approved_by_fkey
    foreign key (approved_by) references auth.users(id) on delete set null;

-- 2d. updated_at trigger
drop trigger if exists action_queue_set_updated_at on public.action_queue;
create trigger action_queue_set_updated_at
  before update on public.action_queue
  for each row execute function public.set_updated_at();

-- 2e. Indices for the worker's polling fallback and dependency lookups
create index if not exists action_queue_status_idx on public.action_queue (status);
create index if not exists action_queue_approved_status_idx on public.action_queue (approved, status);
create index if not exists action_queue_sequence_num_idx on public.action_queue (sequence_num);

-- -----------------------------------------------------------------------------
-- 3. Lock down RLS — drop permissive anon policies, add authenticated-only
-- -----------------------------------------------------------------------------

-- 3a. Drop ALL existing policies on these tables
do $$
declare
  pol record;
begin
  for pol in
    select schemaname, tablename, policyname
    from pg_policies
    where schemaname = 'public'
      and tablename in ('action_queue', 'messages', 'mac_heartbeat', 'inventory')
  loop
    execute format('drop policy if exists %I on %I.%I',
                   pol.policyname, pol.schemaname, pol.tablename);
  end loop;
end$$;

-- 3b. Ensure RLS is enabled
alter table public.action_queue   enable row level security;
alter table public.messages       enable row level security;
alter table public.mac_heartbeat  enable row level security;
alter table public.inventory      enable row level security;

-- 3c. authenticated-role policies (single-user system: any logged-in user = you)
create policy authenticated_all_action_queue on public.action_queue
  for all to authenticated using (auth.uid() is not null) with check (auth.uid() is not null);

create policy authenticated_all_messages on public.messages
  for all to authenticated using (auth.uid() is not null) with check (auth.uid() is not null);

create policy authenticated_read_heartbeat on public.mac_heartbeat
  for select to authenticated using (auth.uid() is not null);

create policy authenticated_all_inventory on public.inventory
  for all to authenticated using (auth.uid() is not null) with check (auth.uid() is not null);

-- 3d. NO anon policies. Anon role has zero access to these tables.
-- 3e. service_role bypasses RLS automatically in Supabase — no explicit policies needed.
--     (The previous "Service role full access" policies scoped to {public} were a bug;
--      removed above. service_role will continue to work via its bypass privilege.)

-- -----------------------------------------------------------------------------
-- 4. Realtime publication — ensure action_queue, messages are published
-- -----------------------------------------------------------------------------
do $$
begin
  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime' and tablename = 'action_queue'
  ) then
    alter publication supabase_realtime add table public.action_queue;
  end if;
  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime' and tablename = 'messages'
  ) then
    alter publication supabase_realtime add table public.messages;
  end if;
end$$;

-- Set REPLICA IDENTITY FULL so UPDATE events carry the full row (worker needs it)
alter table public.action_queue replica identity full;
alter table public.messages     replica identity full;
