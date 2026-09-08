-- Finish the Phase 3 prune: drop the tables whose code went months ago.
--
-- Phase 3 removed the features — Inventory, news_fetch, the old travel_routes
-- cache — and deleted their code. It did not drop their tables, so four have
-- sat in the schema since, empty and unreferenced. Confirmed before writing
-- this, both ways:
--
--   select count(*) from inventory / news_items / travel_routes / expenses
--     → 0, 0, 0, 0
--   grep for each name across apps/worker and apps/web/src
--     → no hits at all
--
-- Not tidiness. An empty table that nothing reads is a trap for the next
-- person: it looks like a feature that exists, so a reasonable reader wires
-- something to it, or spends an afternoon working out why it is always empty.
-- This project has already lost time to exactly that shape of thing —
-- `mac_heartbeat.status` was a column nobody could explain for an afternoon.
--
-- `expenses` never had code at all; it was created in the phase 1 foundation
-- migration alongside health_logs and no executor was ever written for it.
--
-- Reversible: each was created by a migration still in this directory, so
-- restoring one is re-running that CREATE. No data is lost because there is
-- none.

drop table if exists public.inventory;
drop table if exists public.news_items;
drop table if exists public.travel_routes;
drop table if exists public.expenses;

-- notifications is deliberately NOT dropped. It was in the same state — read
-- by the notification bell, written by nothing — but the answer there is the
-- opposite one: it is now the in-app channel the worker writes to, chosen over
-- the public ntfy topic for anything specific about where the user is going.
-- See executors/notify_ops.py `notify()`.
--
-- It needs the index the bell's query actually uses, which it never had.
create index if not exists notifications_user_created_idx
    on public.notifications (user_id, created_at desc);

-- One index, not two. An unread index was added here as well and dropped again
-- minutes later: `idx_notifications_user_unread` on (user_id, read) WHERE
-- read = false already existed and already covers that query. A duplicate
-- index is write cost and disk for nothing, and the only reason it got written
-- is that nobody looked at the table's existing indexes first.
