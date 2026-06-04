INSERT INTO scheduled_jobs (id, job_name, cron_expr, timezone, config)
VALUES (gen_random_uuid(), 'task_tracker', '0 * * * *', 'UTC', '{"description": "Proactive task reminders hourly"}')
ON CONFLICT (job_name) DO NOTHING;
