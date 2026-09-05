-- health_logs: an upsert key PostgREST can actually target, and a user on
-- every row.
--
-- The third table in this project with the same fault. `nearby_services` (#39)
-- and `user_location` (#49) both had a key the client could not name, and both
-- failed the same way: PostgREST emits a plain `ON CONFLICT (a, b, c)`, which
-- Postgres cannot match to an EXPRESSION index, so every write died with
-- 42P10. Here it is `COALESCE(meal_type, '__none__')`.
--
-- This table hid it better than the other two, because nothing ever wrote
-- `user_id`. NULLs are distinct under a unique index, so nine rows accumulated
-- with the constraint silently inert — and the moment a user_id was written,
-- the second glass of water of any day would have failed. The constraint was
-- not wrong; it had simply never been enforced.
--
-- One row per (user, day, metric, meal type) is the right model for both
-- metrics this table actually carries: water is a running daily total, and a
-- meal is one lunch per day. So the rule stays and only its SHAPE changes.

-- 1. Merge the duplicates the inert constraint allowed, so the unique
--    constraint below can be created at all. Water sums; anything else keeps
--    its earliest row. Done before user_id is set, while the rows are still
--    reachable only by their NULL user.
with ranked as (
    select id,
           row_number() over (
               partition by log_date, metric, coalesce(meal_type, '__none__')
               order by created_at
           ) as rn,
           sum(value) over (
               partition by log_date, metric, coalesce(meal_type, '__none__')
           ) as merged_value
    from public.health_logs
    where user_id is null
)
update public.health_logs h
set value = r.merged_value
from ranked r
where h.id = r.id and r.rn = 1;

delete from public.health_logs h
using (
    select id,
           row_number() over (
               partition by log_date, metric, coalesce(meal_type, '__none__')
               order by created_at
           ) as rn
    from public.health_logs
    where user_id is null
) r
where h.id = r.id and r.rn > 1;

-- 2. Adopt the orphans. A single-user deployment, and utils.resolve_user
--    raises if a second one ever appears, so there is exactly one owner these
--    rows can belong to.
update public.health_logs
set user_id = (select user_id from public.user_profile limit 1)
where user_id is null;

-- 3. '' rather than NULL for "not a meal", so the key is a plain column list.
--    '' already meant this via the COALESCE; the migration only makes it
--    explicit, exactly as #39 did for headsign.
--
--    Order matters and is not obvious: the existing check permits NULL or one
--    of four meal names, and NOT ''. Rewriting the rows before dropping it
--    fails on the first row. Drop, rewrite, then re-add the wider check.
alter table public.health_logs
    drop constraint if exists health_logs_meal_type_check;

update public.health_logs set meal_type = '' where meal_type is null;

alter table public.health_logs
    alter column meal_type set default '',
    alter column meal_type set not null;

alter table public.health_logs
    add constraint health_logs_meal_type_check
    check (meal_type in ('', 'breakfast', 'lunch', 'dinner', 'snack'));

-- 4. The key itself: a plain unique constraint, nameable by the client.
drop index if exists public.health_logs_user_date_metric_meal_unique;

alter table public.health_logs
    drop constraint if exists health_logs_user_date_metric_unique;

alter table public.health_logs
    add constraint health_logs_user_date_metric_meal_unique
    unique (user_id, log_date, metric, meal_type);

-- 5. And close the hole that let the constraint sit inert for three months.
--    A unique index permits any number of NULLs, so a NULL user_id exempted
--    every row from the rule above — which is precisely what happened. NOT
--    NULL is what makes this fix hold; without it the same bug can walk back
--    in through any writer that forgets the column.
--
--    The foreign key has to change with it: ON DELETE SET NULL cannot coexist
--    with NOT NULL. CASCADE is the honest behaviour for a personal log — if
--    the account is gone, so is its health history.
alter table public.health_logs
    drop constraint if exists health_logs_user_id_fkey;

alter table public.health_logs
    alter column user_id set not null;

alter table public.health_logs
    add constraint health_logs_user_id_fkey
    foreign key (user_id) references auth.users(id) on delete cascade;
