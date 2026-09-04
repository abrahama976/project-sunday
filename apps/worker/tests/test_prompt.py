"""What every system prompt has to carry, whatever else changes in it.

Only one thing so far, and it is the one that was missing: the current date.

Without it the model dates from its training data. Asked for "Blacktown
tomorrow 7am" it wrote 2024-05-15, handed that to trip_plan, and TfNSW answered
a question about May 2024 without complaint — a journey planned, in good faith,
eighteen months into the past. Every briefing prompt in jobs.py already carried
a date. The chat path, the only one that takes relative dates from a human, was
the one without.

Deliberately its own file rather than an addition to test_agent_loop.py: that
suite builds real google.genai Content objects and skips wholesale when the
worker's dependencies are absent, so an assertion added there would quietly
never run in a bare checkout. This runs on the harness, so it runs anywhere.

    python3 tests/test_prompt.py
"""
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(__file__))
from _harness import setup  # noqa: E402
setup()

from config import USER_TIMEZONE      # noqa: E402
from router import build_system_prompt  # noqa: E402

failures = []


def check_true(label, cond, detail=""):
    if cond:
        print(f"  ok  {label}")
    else:
        failures.append(f"{label}{('  — ' + detail) if detail else ''}")


print("\n── the system prompt knows what day it is ────────────")

prompt = build_system_prompt()
today = datetime.now(ZoneInfo(USER_TIMEZONE))

check_true("the prompt states the current year", str(today.year) in prompt)
check_true("...and the full date", today.strftime("%d %B %Y") in prompt)
check_true("...and the weekday", today.strftime("%A") in prompt)
check_true("...and the timezone it is all in", USER_TIMEZONE in prompt)

# First line, because a date stated after four hundred lines of instructions is
# a date the model has already had every chance to ignore.
check_true("...on the very first line, so it is read first",
           prompt.startswith("NOW: "),
           f"starts with {prompt[:40]!r}")

check_true("...and says relative dates resolve against it, by name",
           "'tomorrow'" in prompt and "relative to NOW" in prompt)

# Rebuilt per call, not memoised. context/loader.py caches the profile and the
# directives — the database reads — and not this string, so there is no stale
# copy to invalidate when the date rolls over at midnight.
check_true("the prompt is rebuilt on every call, so the date cannot go stale",
           build_system_prompt() is not prompt)

# The timezone is the configured one rather than a literal, so a move does not
# leave a second, contradictory answer buried in the calendar section.
check_true("the calendar instruction uses the configured timezone too",
           f"Use the {USER_TIMEZONE} timezone" in prompt)

print()
if failures:
    print(f"✗ {len(failures)} failure(s):\n")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("✓ all prompt tests passed")
