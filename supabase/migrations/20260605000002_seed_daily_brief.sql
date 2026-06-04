INSERT INTO scheduled_jobs (job_name, cron_expr, timezone, enabled)
VALUES ('daily_brief', '0 8 * * *', 'Australia/Sydney', true)
ON CONFLICT (job_name) DO UPDATE 
SET cron_expr = EXCLUDED.cron_expr, timezone = EXCLUDED.timezone;
