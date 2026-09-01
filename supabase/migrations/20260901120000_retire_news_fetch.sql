-- Retire the news_fetch scheduled job (Phase 3).
--
-- Required, not cosmetic: `executors/news_ops.py` is gone and main.py no longer
-- registers a handler, so an enabled row here means the scheduler logs an
-- unhandled job on every tick it matches.
--
-- Disabled rather than deleted. The row is the record of what this job was and
-- when it last ran, and re-enabling is a one-line UPDATE if news ever comes
-- back. `news_items` is left in place with its data.

UPDATE public.scheduled_jobs
   SET enabled = false
 WHERE job_name = 'news_fetch';
