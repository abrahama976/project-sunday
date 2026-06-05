"""Cron-like scheduler for recurring worker jobs.

Runs alongside the existing poll loop as an asyncio task.
Job definitions are stored in the `scheduled_jobs` Supabase table.
Each tick (every 30s), checks for due jobs and executes them.
"""
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from supabase import Client


def _cron_matches(cron_expr: str, dt: datetime) -> bool:
    """Check if a cron expression matches the given datetime.

    Supports standard 5-field cron: minute hour day-of-month month day-of-week
    Supports: exact values, *, */N, comma-separated values, ranges (A-B).
    """
    fields = cron_expr.strip().split()
    if len(fields) != 5:
        return False

    checks = [
        (fields[0], dt.minute, 0, 59),    # minute
        (fields[1], dt.hour, 0, 23),       # hour
        (fields[2], dt.day, 1, 31),        # day of month
        (fields[3], dt.month, 1, 12),      # month
        (fields[4], dt.isoweekday() % 7, 0, 6),  # day of week (0=Sun)
    ]

    for field, value, min_val, max_val in checks:
        if not _field_matches(field, value, min_val, max_val):
            return False
    return True


def _field_matches(field: str, value: int, min_val: int, max_val: int) -> bool:
    """Check if a single cron field matches a value."""
    if field == "*":
        return True

    for part in field.split(","):
        part = part.strip()

        # Step: */N or A-B/N
        if "/" in part:
            range_part, step_str = part.split("/", 1)
            step = int(step_str)
            if range_part == "*":
                if value % step == 0:
                    return True
            elif "-" in range_part:
                start, end = map(int, range_part.split("-", 1))
                if start <= value <= end and (value - start) % step == 0:
                    return True
            continue

        # Range: A-B
        if "-" in part:
            start, end = map(int, part.split("-", 1))
            if start <= value <= end:
                return True
            continue

        # Exact value
        if int(part) == value:
            return True

    return False


def _get_previous_fire_time(cron_expr: str, reference_dt: datetime) -> datetime | None:
    """
    Walk backward minute-by-minute (max 1440 steps = 24h) to find
    the most recent past minute that matches this cron expression.
    Returns None if no match found in 24h window.
    """
    from datetime import timedelta
    candidate = reference_dt.replace(second=0, microsecond=0) - timedelta(minutes=1)
    for _ in range(1440):
        if _cron_matches(cron_expr, candidate):
            return candidate
        candidate -= timedelta(minutes=1)
    return None


class Scheduler:
    """Cron-like scheduler that reads jobs from the scheduled_jobs table."""

    def __init__(self, client: Client, gemini_api_key: str):
        self._client = client
        self._gemini_api_key = gemini_api_key
        self._handlers: dict[str, object] = {}

    def register_handler(self, job_name: str, handler):
        """Register an async handler function for a job name."""
        self._handlers[job_name] = handler

    async def run(self, check_interval: int = 30):
        """Main loop — check for due jobs every `check_interval` seconds."""
        print("[scheduler] started")

        while True:
            try:
                await self._tick()
            except Exception as e:
                print(f"[scheduler] tick error: {e}")

            await asyncio.sleep(check_interval)

    async def _tick(self):
        """Check all enabled jobs and run any that are due."""
        result = await asyncio.to_thread(
            lambda: self._client.table("scheduled_jobs")
            .select("*")
            .eq("enabled", True)
            .execute()
        )

        jobs = result.data or []
        now = datetime.now(ZoneInfo("Australia/Sydney"))
        # Round to the current minute (ignore seconds)
        now_minute = now.replace(second=0, microsecond=0)

        for job in jobs:
            job_name = job.get("job_name", "")
            cron_expr = job.get("cron_expr", "")
            tz_name = job.get("timezone", "Australia/Sydney")
            last_run = job.get("last_run_at")

            if not cron_expr:
                continue

            # Use job's timezone if different
            try:
                tz = ZoneInfo(tz_name)
                check_time = datetime.now(tz).replace(second=0, microsecond=0)
            except Exception:
                check_time = now_minute

            # Prevent double-execution within the same minute
            if last_run:
                try:
                    last_dt = datetime.fromisoformat(last_run)
                    if last_dt.replace(second=0, microsecond=0) >= check_time.replace(second=0, microsecond=0):
                        continue
                except (ValueError, TypeError):
                    pass

            # Catch-up: if last_executed_at is missing or stale, fire immediately
            # even if cron doesn't match right now (Mac was asleep)
            last_executed = job.get("last_executed_at")
            if last_executed:
                try:
                    last_exec_dt = datetime.fromisoformat(last_executed)
                    prev_fire = _get_previous_fire_time(cron_expr, check_time)
                    if prev_fire and last_exec_dt < prev_fire:
                        # Missed a fire — run as catch-up
                        print(f"[scheduler] catch-up firing job: {job_name} "
                              f"(last_executed={last_exec_dt.isoformat()}, "
                              f"expected={prev_fire.isoformat()})")
                        # Fall through to execute below
                    else:
                        # Already ran since last expected fire — skip if cron doesn't match
                        if not _cron_matches(cron_expr, check_time):
                            continue
                except (ValueError, TypeError):
                    if not _cron_matches(cron_expr, check_time):
                        continue
            else:
                if not _cron_matches(cron_expr, check_time):
                    continue

            # Execute the job
            handler = self._handlers.get(job_name)
            if handler:
                print(f"[scheduler] running job: {job_name}")
                try:
                    asyncio.create_task(self._run_job(job, handler))
                except Exception as e:
                    print(f"[scheduler] failed to start job {job_name}: {e}")
            else:
                print(f"[scheduler] no handler for job: {job_name}")

    async def _run_job(self, job: dict, handler):
        """Execute a job handler and update last_run_at."""
        job_name = job.get("job_name", "unknown")
        try:
            await handler(self._client, self._gemini_api_key)

            # Update last_run_at
            now_iso = datetime.now(ZoneInfo("Australia/Sydney")).isoformat()
            await asyncio.to_thread(
                lambda: self._client.table("scheduled_jobs").update({
                    "last_run_at": now_iso,
                    "last_executed_at": now_iso,
                }).eq("id", job["id"]).execute()
            )

            print(f"[scheduler] completed job: {job_name}")
        except Exception as e:
            print(f"[scheduler] job {job_name} failed: {e}")
