-- Two scheduled jobs: look further ahead, and learn from what was planned.
--
-- travel_preview (20:00 local)
--   `travel_watch` runs every five minutes with a SIX-HOUR horizon, which is
--   right for a leave-now alert and useless for the question actually asked in
--   the evening: is tomorrow going to be a problem. An 8am event stayed
--   invisible until 2am, by which time "leave at 6:40" helps nobody. This runs
--   once, over tomorrow's located events, and writes ONE message covering the
--   day rather than one per event.
--
-- travel_learn (03:30 local)
--   Notices destinations planned on three or more different days and offers to
--   remember them. It only ever QUEUES an approve-tier `save_place` — it never
--   writes to saved_places itself, because that table is read by every later
--   trip, so a wrong guess at "work" silently redirects every future answer
--   instead of failing once and visibly.
--
-- Local hours against the timezone column, never pre-converted to UTC: the
-- scheduler honours `timezone`, and pre-converting drifts under DST.

insert into public.scheduled_jobs (job_name, cron_expr, timezone, enabled, config)
values
  ('travel_preview', '0 20 * * *', 'Australia/Sydney', true,
   '{"description": "Plan tomorrow''s located events and post one summary in the evening"}'::jsonb),
  ('travel_learn', '30 3 * * *', 'Australia/Sydney', true,
   '{"description": "Offer to remember destinations planned on 3+ different days"}'::jsonb)
on conflict (job_name) do update
  set cron_expr = excluded.cron_expr,
      timezone  = excluded.timezone,
      enabled   = excluded.enabled;
