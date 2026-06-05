-- Insert the daily_brief scheduled job if it does not already exist.
-- Cron: 22:00 UTC = 08:00 AEST (Sydney).
-- The scheduler in scheduler.py reads this table every 30 seconds.
INSERT INTO public.scheduled_jobs (job_name, cron_expr, enabled, config)
VALUES (
  'daily_brief',
  '0 22 * * *',
  true,
  '{"description": "Morning brief: weather + calendar + tasks + email summary. Runs at 08:00 AEST."}'::jsonb
)
ON CONFLICT (job_name) DO NOTHING;
