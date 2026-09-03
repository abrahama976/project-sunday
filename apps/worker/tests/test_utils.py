"""Tests for utils.row, display_name, resolve_user and resolve_origin.

Each exists because of a live bug or a live assumption, so each is worth
pinning. Ordinary imports via `_harness.setup()`, which stubs the uninstalled
packages that utils drags in for helpers these tests do not touch.

The real `asyncio.to_thread` is used rather than a stand-in: the fake clients
below are synchronous, and to_thread runs them faithfully in a worker thread.

    python3 tests/test_utils.py
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))
from _harness import setup  # noqa: E402
setup()

from utils import (                                   # noqa: E402
    row, display_name, resolve_user, resolve_origin, as_datetime, MultipleUsers,
)

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


class Res:
    def __init__(self, data):
        self.data = data


PROFILE = (
    "# About Me\n"
    "**Name:** Abraham\n"
    "**Location:** Sydney, Australia (UTC+10, Australia/Sydney)\n"
)


print("\n── row() ─────────────────────────────────────────────")

# maybe_single() returns None itself when nothing matched — not a response
# object with data=None. This is the distinction that crashed calendar_prep.
check("None result is an empty dict", row(None), {})
check("data=None is an empty dict", row(Res(None)), {})
check("a real row passes through", row(Res({"name": "Abraham"})), {"name": "Abraham"})
check("an empty row is an empty dict", row(Res({})), {})


print("\n── display_name() ────────────────────────────────────")

# The live shape: the column is NULL, the name is in the markdown. This is the
# case that produced "## Good morning, None ☀️" every morning.
check("NULL column falls back to the profile body",
      display_name({"name": None, "content": PROFILE}), "Abraham")
check("...and never returns the string 'None'",
      display_name({"name": None, "content": PROFILE}) == "None", False)
check("the column wins when it is set",
      display_name({"name": "Alstone", "content": PROFILE}), "Alstone")
check("an empty-string column is not a name",
      display_name({"name": "   ", "content": PROFILE}), "Abraham")

check("no name anywhere falls back",
      display_name({"name": None, "content": "# About Me\nNo name here.\n"}), "there")
check("an empty profile falls back", display_name({}), "there")
check("a custom fallback is honoured", display_name({}, fallback="friend"), "friend")

# A greeting wants a first name, not a full one.
check("a full name is cut to the first",
      display_name({"name": None, "content": "**Name:** Abraham Alstone\n"}), "Abraham")
check("surrounding whitespace is trimmed",
      display_name({"name": None, "content": "**Name:**    Abraham   \n"}), "Abraham")

# The H1 is "# About Me" — matching it is what made the web app say
# "Hey, About Me." The name line is the only thing worth reading.
check("the H1 heading is not mistaken for the name",
      display_name({"name": None, "content": PROFILE}) == "About", False)

# The name line does not have to be the first line, or the only bold line.
check("the name line is found further down",
      display_name({"name": None, "content": "# About Me\n**Location:** Sydney\n**Name:** Abraham\n"}),
      "Abraham")

print("\n── resolve_user() ────────────────────────────────────")


class FakeClient:
    """Just enough supabase-py to satisfy resolve_user's one query."""

    def __init__(self, profiles):
        self._profiles = profiles

    def table(self, _name):
        return self

    def select(self, _cols):
        return self

    def execute(self):
        return Res(self._profiles)


def resolved(profiles):
    return asyncio.run(resolve_user(FakeClient(profiles)))


def raises(profiles):
    try:
        resolved(profiles)
        return None
    except MultipleUsers as e:
        return str(e)


ONE = [{"user_id": "u-1", "name": None, "content": PROFILE}]

check("the single user resolves", resolved(ONE)["user_id"], "u-1")
check("...with a real name, not the NULL column", resolved(ONE)["name"], "Abraham")
check("...and carries the profile body", resolved(ONE)["content"].startswith("# About Me"), True)

check("the column wins when it is populated",
      resolved([{"user_id": "u-1", "name": "Alstone", "content": PROFILE}])["name"], "Alstone")
check("no name anywhere still resolves the id",
      resolved([{"user_id": "u-1", "name": None, "content": ""}])["name"], "there")

# The guard that replaces the deleted fan-out. Serving only the first of two
# users silently is the failure this exists to prevent.
two = [{"user_id": "u-1", "content": PROFILE}, {"user_id": "u-2", "content": PROFILE}]
check_true("two users raise", raises(two) is not None)
check_true("...and the message says how many", "2 user profiles" in (raises(two) or ""))
check_true("...and names the fix", "fan-out" in (raises(two) or ""))

check_true("zero users raise", raises([]) is not None)
check_true("rows without a user_id do not count",
           raises([{"user_id": None, "content": PROFILE}]) is not None)
check("one real row beside a null one still resolves",
      resolved([{"user_id": None}, {"user_id": "u-1", "content": PROFILE}])["user_id"], "u-1")


print("\n── resolve_origin() ──────────────────────────────────")


class PlacesClient:
    """user_location and saved_places, both reached through .table()."""

    def __init__(self, live=None, place=None):
        self._live, self._place = live, place
        self._target = None

    def table(self, name):
        self._target = name
        return self

    def select(self, _cols):
        return self

    def eq(self, *_a):
        return self

    def limit(self, _n):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        # supabase-py returns None itself when maybe_single matches nothing.
        data = self._live if self._target == "user_location" else self._place
        return Res(data) if data is not None else None


def origin_of(live=None, place=None):
    return asyncio.run(resolve_origin(PlacesClient(live, place), "u-1"))


def ago(minutes):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


HOME = {"label": "home", "address": "1 Test St", "lat": -33.9, "lng": 151.1}

# A fresh fix wins: you are somewhere, and that somewhere is where you start.
fresh = origin_of(live={"lat": -33.86, "lng": 151.2, "updated_at": ago(2)}, place=HOME)
check("a fresh GPS fix is used", fresh["origin"], "-33.86,151.2")
check("...and says so", fresh["source"], "your current location")

# A stale one does not. This is the case that matters: an old fix looks current
# and would silently route you from the wrong suburb.
stale = origin_of(live={"lat": -33.86, "lng": 151.2, "updated_at": ago(120)}, place=HOME)
check("a stale fix falls back to the saved place", stale["origin"], "-33.9,151.1")
check("...and names the place", stale["source"], "home")

check("no live row at all falls back", origin_of(place=HOME)["origin"], "-33.9,151.1")
check("a live row with no coordinates falls back",
      origin_of(live={"lat": None, "lng": None, "updated_at": ago(1)}, place=HOME)["origin"],
      "-33.9,151.1")
check("an unparseable timestamp is treated as stale",
      origin_of(live={"lat": -33.86, "lng": 151.2, "updated_at": "not a date"}, place=HOME)["origin"],
      "-33.9,151.1")

# Coordinates beat the address string — they cannot be mis-geocoded.
check("a place without coordinates uses its address",
      origin_of(place={"label": "work", "address": "100 George St"})["origin"],
      "100 George St")

check_true("nothing known at all returns None", origin_of() is None)
check_true("a place with neither address nor coordinates is not an origin",
           origin_of(place={"label": "empty", "address": ""}) is None)



print("\n── as_datetime() ─────────────────────────────────────")

# Supabase returns timestamps as strings. A naive one compared against an aware
# one raises in some orderings and silently misjudges in others, so everything
# that comes back from the database goes through here first.
check("an offset timestamp keeps its offset",
      as_datetime("2026-09-02T08:00:00+10:00").utcoffset(), timedelta(hours=10))
check("a Z suffix is understood",
      as_datetime("2026-09-02T08:00:00Z").utcoffset(), timedelta(0))
check("a naive timestamp is assumed UTC — what Postgres stored",
      as_datetime("2026-09-02T08:00:00").utcoffset(), timedelta(0))
check_true("None round-trips as None", as_datetime(None) is None)
check_true("an empty string is not a time", as_datetime("") is None)
check_true("nonsense is not a time, and does not raise",
           as_datetime("not a timestamp") is None)

print()
if failures:
    print(f"✗ {len(failures)} failure(s):\n")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("✓ all utils tests passed")
