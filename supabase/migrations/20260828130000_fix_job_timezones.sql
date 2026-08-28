-- Scheduler timezone corrections.
--
-- scheduler.py:_tick() honours the `timezone` column
-- (check_time = datetime.now(ZoneInfo(tz_name))), so the correct fix is to
-- store LOCAL hours against 'Australia/Sydney' rather than pre-converting to
-- UTC. Pre-converted UTC hours are also DST-fragile: Sydney is UTC+10 in AEST
-- and UTC+11 in AEDT, so any fixed UTC hour drifts by an hour twice a year.

-- meal_checkin was seeded as '0 13,19 * * *' in UTC — the hours were written
-- as if they were local. In AEST that fired at 23:00 and 05:00 Sydney time.
UPDATE public.scheduled_jobs
   SET cron_expr = '0 13,19 * * *',
       timezone  = 'Australia/Sydney'
 WHERE job_name = 'meal_checkin';

-- daily_brief was seeded as '0 22 * * *' UTC to mean 08:00 AEST. Correct in
-- winter, an hour late (09:00) through AEDT.
UPDATE public.scheduled_jobs
   SET cron_expr = '0 8 * * *',
       timezone  = 'Australia/Sydney'
 WHERE job_name = 'daily_brief';

-- cold_storage_archive: weekly Sunday 03:00, seeded in UTC (= 13:00 Sydney,
-- i.e. the middle of Sunday afternoon rather than overnight).
UPDATE public.scheduled_jobs
   SET cron_expr = '0 3 * * 0',
       timezone  = 'Australia/Sydney'
 WHERE job_name = 'cold_storage_archive';
