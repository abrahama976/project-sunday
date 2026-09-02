"""Tests for the scheduler's in-flight guard and cron matching.

Dependency-free: the pure cron helpers are loaded straight from source, and the
in-flight behaviour is exercised against a hand-rolled stand-in that mirrors
Scheduler's tick/run structure. Importing the real Scheduler would drag in
supabase, which these do not need.

    python3 tests/test_scheduler.py
"""
import ast
import asyncio
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timedelta

_SRC = open(os.path.join(os.path.dirname(__file__), "..", "scheduler.py")).read()
# datetime is in scope because the extracted functions carry type annotations
# that are evaluated at definition time.
_g = {"re": re, "datetime": datetime, "timedelta": timedelta, "__name__": "pure"}
_tree = ast.parse(_SRC)
_keep = [n for n in _tree.body
         if isinstance(n, ast.FunctionDef)
         and n.name in {"_cron_matches", "_field_matches"}]
exec(compile(ast.Module(body=_keep, type_ignores=[]), "scheduler.py", "exec"), _g)
_cron_matches = _g["_cron_matches"]

failures = []


def check(label, actual, expected):
    if actual != expected:
        failures.append(f"{label}\n     expected: {expected!r}\n     actual:   {actual!r}")
    else:
        print(f"  ok  {label}")


def check_true(label, cond, detail=""):
    if not cond:
        failures.append(f"{label} {detail}")
    else:
        print(f"  ok  {label}")


print("\n── cron matching ──────────────────────────────────────")

check("meal_checkin fires at 13:00", _cron_matches("0 13,19 * * *", datetime(2026, 8, 31, 13, 0)), True)
check("meal_checkin fires at 19:00", _cron_matches("0 13,19 * * *", datetime(2026, 8, 31, 19, 0)), True)
check("meal_checkin quiet at 05:00", _cron_matches("0 13,19 * * *", datetime(2026, 8, 31, 5, 0)), False)
check("daily_brief fires at 08:00", _cron_matches("0 8 * * *", datetime(2026, 8, 31, 8, 0)), True)
check("weekly Sunday-only expression", _cron_matches("0 3 * * 0", datetime(2026, 8, 30, 3, 0)), True)
check("...and not on Monday", _cron_matches("0 3 * * 0", datetime(2026, 8, 31, 3, 0)), False)
check("step expressions", _cron_matches("*/5 * * * *", datetime(2026, 8, 31, 3, 15)), True)
check("malformed expression never matches", _cron_matches("nonsense", datetime(2026, 8, 31, 3, 0)), False)


print("\n── in-flight guard ────────────────────────────────────")


class FakeScheduler:
    """Mirrors the real tick/run split: _tick decides and dispatches, _run_job
    executes and releases. The guard lives across that boundary, which is
    exactly where the bug was."""

    def __init__(self, handler):
        self._in_flight: set[str] = set()
        self._handler = handler
        self.starts = 0

    async def tick(self, job_name="slow_job"):
        if job_name in self._in_flight:
            return False
        self._in_flight.add(job_name)   # before create_task, not inside it
        self.starts += 1
        asyncio.create_task(self._run_job(job_name))
        return True

    async def _run_job(self, job_name):
        try:
            await self._handler()
        except Exception:
            pass
        finally:
            self._in_flight.discard(job_name)

    async def run_now(self, job_name="slow_job"):
        """Off-schedule run, sharing the guard with tick().

        The real one is what startup calls instead of invoking the handler
        directly — a direct call is invisible to _in_flight, which is how
        sync_calendar came to run twice on every start.
        """
        if job_name in self._in_flight:
            return False
        self._in_flight.add(job_name)
        self.starts += 1
        await self._run_job(job_name)     # awaited, unlike tick's create_task
        return True


async def scenario_long_job():
    """A job slower than the tick interval must not be started twice.

    This is the observed failure: returning from a 60-day outage, catch-up
    fired sync_calendar and calendar_prep while the previous run was still
    blocked, and every concurrent copy opened its own OAuth flow.
    """
    async def slow():
        await asyncio.sleep(0.05)

    s = FakeScheduler(slow)
    await s.tick()
    await asyncio.sleep(0)          # let the task start
    second = await s.tick()         # tick again while it is still running
    third = await s.tick()
    check("a second tick does not start the job again", second, False)
    check("nor a third", third, False)
    check("exactly one run started", s.starts, 1)

    await asyncio.sleep(0.1)        # let it finish
    fourth = await s.tick()
    check("it runs again once finished", fourth, True)
    check("two runs total", s.starts, 2)


async def scenario_raising_job():
    """A handler that raises must still release the guard, or that job never
    runs again for the lifetime of the worker — a far worse failure than the
    duplicate it was added to prevent."""
    async def boom():
        raise RuntimeError("calendar_prep failed: 'NoneType' object has no attribute 'data'")

    s = FakeScheduler(boom)
    await s.tick()
    await asyncio.sleep(0.02)
    check_true("guard released after the handler raised", len(s._in_flight) == 0)
    check("the job can run again", await s.tick(), True)


async def scenario_independent_jobs():
    """One job being in flight must not block a different one."""
    async def slow():
        await asyncio.sleep(0.05)

    s = FakeScheduler(slow)
    await s.tick("job_a")
    other = await s.tick("job_b")
    check("a different job is unaffected", other, True)
    check("both started", s.starts, 2)


async def scenario_run_now_vs_tick():
    """The startup race, in miniature.

    Startup fired sync_calendar directly while catch-up dispatched it from the
    tick — two concurrent runs of a job that must not run twice. Routing the
    startup call through run_now puts both on the same guard.
    """
    async def slow():
        await asyncio.sleep(0.05)

    s = FakeScheduler(slow)
    asyncio.create_task(s.run_now())      # startup's run, still going
    await asyncio.sleep(0)
    check("tick does not double-start what run_now is running", await s.tick(), False)
    check("exactly one run", s.starts, 1)

    await asyncio.sleep(0.1)
    check_true("guard released when run_now finished", len(s._in_flight) == 0)
    check("the scheduler can run it again afterwards", await s.tick(), True)


async def scenario_run_now_after_tick():
    """And the other way round: a tick already running blocks the direct call."""
    async def slow():
        await asyncio.sleep(0.05)

    s = FakeScheduler(slow)
    await s.tick()
    await asyncio.sleep(0)
    check("run_now defers to a job already in flight", await s.run_now(), False)
    check("still one run", s.starts, 1)


asyncio.run(scenario_long_job())
asyncio.run(scenario_raising_job())
asyncio.run(scenario_independent_jobs())
asyncio.run(scenario_run_now_vs_tick())
asyncio.run(scenario_run_now_after_tick())

print()
if failures:
    print(f"✗ {len(failures)} failure(s):\n")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("✓ all scheduler tests passed")
