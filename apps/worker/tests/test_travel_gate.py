"""Place resolution and the plausibility gate — the two things that were missing.

Both are pure, so all of this runs without a network or an API key. The
fixtures are not invented: they are the itineraries and lookups that actually
reached the user's phone, which is what makes them worth keeping.

    python3 tests/test_travel_gate.py
"""
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(__file__))
from _harness import setup  # noqa: E402
setup()

from travel.contracts import (PlaceCandidate, RESOLVED, AMBIGUOUS,   # noqa: E402
                              IMPLAUSIBLE, NOT_FOUND)
from travel.resolve import (choose_place, candidate_from_location,   # noqa: E402
                            saved_place_match, MAX_PLACE_KM)
from travel.gate import (rejection_reason, gate_journeys,            # noqa: E402
                         rejection_summary, MAX_SINGLE_WAIT_MIN)
from executors.travel_ops import _coord_pair, haversine_m            # noqa: E402

failures = []


def check(label, actual, expected):
    if actual != expected:
        failures.append(f"{label}\n     expected: {expected!r}\n     actual:   {actual!r}")
    else:
        print(f"  ok  {label}")


def check_true(label, cond, detail=""):
    if cond:
        print(f"  ok  {label}")
    else:
        failures.append(f"{label}{('  — ' + detail) if detail else ''}")


SYD = ZoneInfo("Australia/Sydney")
HOME = (-33.922863, 151.206547)          # 314 Gardeners Rd, Rosebery


def cand(name, lat, lng, *, kind="poi", quality=None, is_best=False):
    """A candidate with its distance from home already measured."""
    return PlaceCandidate(name=name, lat=lat, lng=lng, kind=kind,
                          quality=quality, is_best=is_best,
                          distance_km=haversine_m(HOME, (lat, lng)) / 1000.0)


print("\n── choosing which place was meant ────────────────────")

# The provider answering the question itself. Nothing should override isBest.
newtown = cand("Newtown Station", -33.8983, 151.1795, kind="stop",
               quality=900, is_best=True)
newtown_rd = cand("Newtown Rd", -33.8800, 151.1600, kind="street", quality=980)
got = choose_place("Newtown", [newtown_rd, newtown])
check("isBest wins over a higher match score", got.state, RESOLVED)
check("...and it is the stop that is selected", got.selected.name, "Newtown Station")
check("...with the rest kept as alternatives", len(got.alternatives), 1)

# Sans Souci → Narrabri. 500 km away, and it produced a 1953-minute itinerary.
narrabri = cand("Sans Souci St, Narrabri", -30.3247, 149.7828, quality=800)
got = choose_place("Sans Souci", [narrabri])
check("the only candidate being 500 km away is implausible, not resolved",
      got.state, IMPLAUSIBLE)
check_true("...and the message says how far, so the mistake is visible",
           "km away" in got.reason and "Narrabri" in got.reason)

# ...but with a local one in the list, it simply loses on distance.
sans_souci = cand("Sans Souci", -33.9895, 151.1305, quality=800)
got = choose_place("Sans Souci", [narrabri, sans_souci])
check("a local candidate beats a distant one on the same score",
      got.selected.name, "Sans Souci")
check("...and resolves cleanly", got.state, RESOLVED)

# A genuine tie: same score, same kind, neither marked best, far apart.
a = cand("Newtown", -33.8983, 151.1795, kind="locality", quality=800)
b = cand("Newtown", -34.4200, 150.8900, kind="locality", quality=800)
got = choose_place("Newtown", [a, b])
check("two equal candidates far apart are ambiguous", got.state, AMBIGUOUS)
check_true("...and nothing is selected", got.selected is None)
check_true("...and both are offered", len(got.alternatives) >= 2)

# Two entrances to one station are NOT a tie — asking would be noise.
c = cand("Newtown Station", -33.8983, 151.1795, kind="stop", quality=800)
d = cand("Newtown Station, King St", -33.8990, 151.1801, kind="stop", quality=800)
got = choose_place("Newtown Station", [c, d])
check("two points at the same place resolve rather than ask", got.state, RESOLVED)

check("nothing at all is not_found", choose_place("Zzz", []).state, NOT_FOUND)
check("a list of Nones is not_found",
      choose_place("Zzz", [None, None]).state, NOT_FOUND)

# An explicitly long trip is allowed past the distance rule.
got = choose_place("Narrabri", [narrabri], allow_long_distance=True)
check("a long trip asked for on purpose is allowed", got.state, RESOLVED)

# With no origin there is no distance to judge, and a place is not rejected for
# being unmeasurable.
no_distance = PlaceCandidate(name="Somewhere", lat=-30.0, lng=149.0, quality=800)
check("an unmeasured candidate is not rejected for distance",
      choose_place("Somewhere", [no_distance]).state, RESOLVED)


print("\n── parsing what EFA sends ────────────────────────────")

loc = {"id": "10101", "name": "Newtown Station", "disassembledName": "Newtown",
       "type": "stop", "coord": [-33.8983, 151.1795],
       "matchQuality": 950, "isBest": True}
parsed = candidate_from_location(loc, _coord_pair, HOME, haversine_m)
check("the short name is preferred when present", parsed.name, "Newtown")
check("the match score comes through", parsed.quality, 950)
check("isBest comes through", parsed.is_best, True)
check_true("distance is measured from the origin",
           3.0 < parsed.distance_km < 5.0, f"got {parsed.distance_km}")
check("a location with no coordinate parses to None",
      candidate_from_location({"id": "x", "name": "y"}, _coord_pair), None)
check("a non-numeric match score degrades to None rather than raising",
      candidate_from_location({"coord": [-33.9, 151.2], "matchQuality": "high"},
                              _coord_pair).quality, None)


print("\n── saved place labels ────────────────────────────────")

PLACES = [{"label": "home", "address": "314 Gardeners Rd", "lat": -33.92, "lng": 151.20},
          {"label": "work", "address": "1 Martin Pl", "lat": -33.86, "lng": 151.21}]

check("'home' matches the saved place",
      (saved_place_match("home", PLACES) or {}).get("label"), "home")
check("case and spacing do not matter",
      (saved_place_match("  Home ", PLACES) or {}).get("label"), "home")
check("'my home' matches too",
      (saved_place_match("my home", PLACES) or {}).get("label"), "home")
check("'work' matches its own place",
      (saved_place_match("work", PLACES) or {}).get("label"), "work")
check("a real place name is not a label", saved_place_match("Newtown", PLACES), None)
check("an empty string matches nothing", saved_place_match("", PLACES), None)
check("no saved places matches nothing", saved_place_match("home", []), None)


print("\n── the plausibility gate ─────────────────────────────")

NOW = datetime(2026, 9, 4, 19, 0, tzinfo=SYD)


def journey(depart_min, arrive_min, wait=0, duration=None):
    depart = NOW + timedelta(minutes=depart_min)
    arrive = NOW + timedelta(minutes=arrive_min)
    return {"depart": depart, "arrive": arrive, "wait_min": wait,
            "duration_min": duration if duration is not None
            else (arrive - depart).total_seconds() / 60.0}


# THE ONE FROM TODAY. leave 6:20 PM, arrive 3:07 PM — 1248 min, 783 waiting.
# It was shown as "Best option".
todays_answer = {
    "depart": datetime(2026, 9, 4, 18, 20, tzinfo=SYD),
    "arrive": datetime(2026, 9, 4, 15, 7, tzinfo=SYD),
    "duration_min": 1248, "wait_min": 783, "changes": 4,
}
reason = rejection_reason(todays_answer, NOW)
check_true("the 1248-minute answer is rejected", reason is not None)
check("...for the reason that needs no threshold at all",
      reason, "it arrives before it departs")

# THE WERRIS CREEK ONE. 1953 min, 1260 waiting, for a 15 km trip.
werris_creek = journey(5, 1958, wait=1260, duration=1953)
check_true("the Werris Creek itinerary is rejected",
           rejection_reason(werris_creek, NOW) is not None)
# It fails several rules independently; strip them one at a time to prove the
# gate does not depend on any single one catching it.
check_true("...on waiting alone",
           rejection_reason({**werris_creek, "duration_min": 60}, NOW) is not None)
check_true("...on duration alone",
           rejection_reason({**werris_creek, "wait_min": 0}, NOW) is not None)
check_true("...and on arriving a day later alone",
           rejection_reason({**werris_creek, "wait_min": 0, "duration_min": 60},
                            NOW) is not None)

# A real journey passes untouched. Today's good answer: 35 min, 9 min waiting.
good = journey(23, 58, wait=9)
check("the 35-minute answer survives", rejection_reason(good, NOW), None)
check("...and against a 10-minute drive", rejection_reason(good, NOW, None, 10), None)

# Boundaries, both sides.
check("a wait of exactly the cap is allowed",
      rejection_reason(journey(0, 200, wait=MAX_SINGLE_WAIT_MIN), NOW), None)
check_true("one minute over the cap is not",
           rejection_reason(journey(0, 200, wait=MAX_SINGLE_WAIT_MIN + 1),
                            NOW) is not None)
check("waiting exactly half the journey is allowed",
      rejection_reason(journey(0, 60, wait=30), NOW), None)
check_true("more than half is not",
           rejection_reason(journey(0, 60, wait=31), NOW) is not None)
check("four times the drive is allowed",
      rejection_reason(journey(0, 40, wait=5), NOW, None, 10), None)
check_true("more than four times is not",
           rejection_reason(journey(0, 41, wait=5), NOW, None, 10) is not None)

check_true("a departure in the past is rejected",
           rejection_reason(journey(-5, 30), NOW) is not None)
check_true("arriving after the deadline is rejected",
           rejection_reason(journey(5, 60), NOW,
                            NOW + timedelta(minutes=30)) is not None)
check("...and before it is fine",
      rejection_reason(journey(5, 25), NOW, NOW + timedelta(minutes=30)), None)
check_true("a journey with no times is rejected",
           rejection_reason({"depart": None, "arrive": None}, NOW) is not None)
check_true("an empty journey is rejected", rejection_reason(None, NOW) is not None)

# Overnight is allowed when it was asked for. Kept short on purpose: a 10-hour
# journey is rejected for its duration whatever the date, and that would prove
# nothing about the overnight rule.
overnight = journey(240, 330, wait=20)          # 23:00 → 00:30, 90 minutes
check_true("a trip crossing midnight is rejected by default",
           rejection_reason(overnight, NOW) is not None)
check("...for arriving on a later day",
      rejection_reason(overnight, NOW),
      "it arrives on a later day, which is not what you asked for")
check("...and allowed when the caller says so",
      rejection_reason(overnight, NOW, None, None, True), None)


print("\n── the gate over a whole set ─────────────────────────")

kept, rejected = gate_journeys([good, todays_answer, werris_creek], NOW)
check("only the real journey survives", len(kept), 1)
check("...and the other two are kept with reasons", len(rejected), 2)
check_true("every rejection carries a reason",
           all(r for _s, r in rejected))

check("an empty set gates to nothing", gate_journeys([], NOW), ([], []))

# Deduplicated: five journeys rejected the same way is one fact, not five.
same = [journey(0, 200, wait=120) for _ in range(5)]
_kept, many = gate_journeys(same, NOW)
check("five identical faults report as one reason",
      rejection_summary(many).count(";"), 0)
check("no rejections summarises to nothing", rejection_summary([]), "")


print()
if failures:
    print(f"✗ {len(failures)} failure(s):\n")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("✓ all resolution and gate tests passed")
