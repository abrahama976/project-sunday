"""Tests for the trip-planning core in executors/travel_ops.py.

The ranking is the part that decides which route you are told to take, so it is
the part worth pinning. Everything under test here is pure — it takes an
already-decoded TfNSW response and returns numbers — so none of this needs a
network, an API key, or the worker's dependencies.

Extracted from source the way test_scheduler.py does, because importing
travel_ops pulls in httpx and config.

    python3 tests/test_travel.py
"""
import ast
import os
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_SRC = open(os.path.join(os.path.dirname(__file__), "..", "executors", "travel_ops.py")).read()
_tree = ast.parse(_SRC)
_WANTED = {
    "_parse_time", "summarise_journey", "_journey_fare",
    "rank_journeys", "describe_alternative", "format_journeys",
    "_as_lonlat", "_route_summary",
}
_keep = [
    n for n in _tree.body
    if (isinstance(n, ast.FunctionDef) and n.name in _WANTED)
    or (isinstance(n, ast.Assign)
        and getattr(n.targets[0], "id", "") in {"_WALK_CLASSES", "_MODE_NAMES",
                                                "_ALT_MAX_LATER_MIN", "_COORD_PAIR",
                                                "_ORS_PROFILES"})
]
_g = {"re": __import__("re"), "__name__": "pure"}
exec(compile(ast.Module(body=_keep, type_ignores=[]), "travel_ops.py", "exec"), _g)
_parse_time = _g["_parse_time"]
summarise_journey = _g["summarise_journey"]
rank_journeys = _g["rank_journeys"]
describe_alternative = _g["describe_alternative"]
format_journeys = _g["format_journeys"]
_as_lonlat = _g["_as_lonlat"]
_route_summary = _g["_route_summary"]

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


SYD = ZoneInfo("Australia/Sydney")
BASE = datetime(2026, 9, 3, 8, 0, tzinfo=SYD)


def t(minutes):
    return (BASE + timedelta(minutes=minutes)).isoformat()


def walk_leg(start, mins, to="Kogarah Station"):
    return {
        "duration": mins * 60,
        "origin": {"name": "Home", "departureTimePlanned": t(start)},
        "destination": {"name": to, "arrivalTimePlanned": t(start + mins)},
        "transportation": {"product": {"class": 100}},
    }


def train_leg(start, mins, line="T4", live=True, frm="Kogarah Station", to="Town Hall Station"):
    origin = {"name": frm, "departureTimePlanned": t(start)}
    dest = {"name": to, "arrivalTimePlanned": t(start + mins)}
    if live:
        origin["departureTimeEstimated"] = t(start)
        dest["arrivalTimeEstimated"] = t(start + mins)
    return {
        "duration": mins * 60,
        "origin": origin,
        "destination": dest,
        "transportation": {"product": {"class": 1}, "disassembledName": line},
    }


print("\n── summarise_journey() ───────────────────────────────")

# Walk 8, train 30, walk 4 — no gaps, so no waiting.
direct = {"legs": [walk_leg(0, 8), train_leg(8, 30), walk_leg(38, 4, to="Office")]}
s = summarise_journey(direct)
check("duration is end to end", s["duration_min"], 42)
check("walking is summed across legs", s["walk_min"], 12)
check("a gapless journey has no waiting", s["wait_min"], 0)
check("one vehicle leg is zero changes", s["changes"], 0)
check_true("a live leg marks the journey real-time", s["realtime"])

# The same trip with 9 minutes standing on the platform.
waiting = {"legs": [walk_leg(0, 8), train_leg(17, 30), walk_leg(47, 4, to="Office")]}
w = summarise_journey(waiting)
check("waiting is the time not moving", w["wait_min"], 9)
check("...and it lengthens the journey", w["duration_min"], 51)

# Two vehicle legs is one change.
two_trains = {"legs": [walk_leg(0, 5), train_leg(5, 20), train_leg(25, 15, line="T8"),
                       walk_leg(40, 3, to="Office")]}
check("two vehicle legs is one change", summarise_journey(two_trains)["changes"], 1)

# A journey built only from the timetable is a guess, and says so.
sched = {"legs": [walk_leg(0, 8), train_leg(8, 30, live=False), walk_leg(38, 4, to="Office")]}
check_true("no estimates means not real-time", summarise_journey(sched)["realtime"] is False)

check_true("a journey with no legs is dropped", summarise_journey({"legs": []}) is None)
check_true("a journey with no usable times is dropped",
           summarise_journey({"legs": [{"duration": 600, "origin": {}, "destination": {},
                                        "transportation": {"product": {"class": 1}}}]}) is None)


print("\n── _parse_time() ─────────────────────────────────────")

# transit_departures used dateutil.parser.isoparse here, which is undeclared in
# requirements.txt AND raises on bad input — one malformed timestamp would take
# the whole departure board down. This returns None instead.
check_true("a Z-suffixed time parses", _parse_time("2026-09-03T08:00:00Z") is not None)
check_true("an offset time parses", _parse_time("2026-09-03T08:00:00+10:00") is not None)
check_true("a naive time is assumed UTC",
           _parse_time("2026-09-03T08:00:00").tzinfo is not None)
check("malformed input is None, not an exception", _parse_time("not a time"), None)
check("None input is None", _parse_time(None), None)
check("empty input is None", _parse_time(""), None)


print("\n── fares ─────────────────────────────────────────────")

fared = dict(direct)
fared["fare"] = {"tickets": [
    {"priceBrutto": 4.71, "properties": {"evaluationTicket": "TICKET_VALID"}},
    {"priceBrutto": 9.99, "properties": {"evaluationTicket": "TICKET_VALID"}},
]}
check("the cheapest valid fare is used", summarise_journey(fared)["fare"], 4.71)
check("no fare block is None, not zero", summarise_journey(direct)["fare"], None)
check("a superseded ticket is ignored",
      summarise_journey({**direct, "fare": {"tickets": [
          {"priceBrutto": 2.0, "properties": {"evaluationTicket": "TICKET_TO_BE_SUPERSEDED"}}]}})["fare"],
      None)


print("\n── rank_journeys() ───────────────────────────────────")

early = summarise_journey({"legs": [walk_leg(0, 5), train_leg(5, 25)]})           # arrives 08:30
late = summarise_journey({"legs": [walk_leg(10, 5), train_leg(15, 25)]})          # arrives 08:40
ranked = rank_journeys([late, early])
check("earliest arrival comes first", ranked[0]["arrive"], early["arrive"])

# Same arrival, different waiting: the one that does not leave you standing wins.
patient = summarise_journey({"legs": [walk_leg(0, 5), train_leg(20, 20)]})        # 15 min wait
brisk = summarise_journey({"legs": [walk_leg(15, 5), train_leg(20, 20)]})         # no wait
check("on a tie, less waiting wins", rank_journeys([patient, brisk])[0]["wait_min"], 0)

check("None summaries are dropped, not crashed on", len(rank_journeys([None, early, None])), 1)
check("an empty list ranks to empty", rank_journeys([]), [])


print("\n── describe_alternative() ────────────────────────────")

best = summarise_journey({"legs": [walk_leg(0, 5), train_leg(5, 20), train_leg(25, 15)]})
fewer = summarise_journey({"legs": [walk_leg(0, 5), train_leg(5, 40)]})
why = describe_alternative(best, fewer)
check_true("a simpler route says so", "1 fewer change" in why, why)

# A later departure is a convenience, not a saving: it is worth offering when
# it costs nothing, and never worth a later arrival on its own.
lie_in = summarise_journey({"legs": [walk_leg(10, 5), train_leg(15, 15)]})        # same arrival
early_start = summarise_journey({"legs": [walk_leg(0, 5), train_leg(5, 25)]})
check_true("a later departure at no cost is offered",
           "leave 10 min later" in describe_alternative(early_start, lie_in),
           describe_alternative(early_start, lie_in))
check_true("...and is described as free",
           "same arrival" in describe_alternative(early_start, lie_in),
           describe_alternative(early_start, lie_in))

slower_lie_in = summarise_journey({"legs": [walk_leg(10, 5), train_leg(15, 25)]})  # 10 min later
check("a later departure alone never pays for a later arrival",
      describe_alternative(early_start, slower_lie_in), "")

# An option that is worse in every way is not an "alternative" worth showing.
check("a strictly worse option gets no pitch", describe_alternative(fewer, best), "")

# Found by reading real output: "5 min less walking — arrives 19 min later" is
# a true reason attached to a bad trade. A minute-denominated saving has to
# cover the minutes it costs.
long_walk = summarise_journey({"legs": [walk_leg(0, 12), train_leg(12, 25)]})     # arrives 08:37
short_walk_slow = summarise_journey({"legs": [walk_leg(0, 4), train_leg(20, 32)]})  # arrives 08:52
check("a small saving does not justify a big delay",
      describe_alternative(long_walk, short_walk_slow), "")

# ...but a saving that outweighs the delay still gets offered.
mild = summarise_journey({"legs": [walk_leg(0, 2), train_leg(3, 36)]})            # arrives 08:39
check_true("a saving worth its delay survives", describe_alternative(long_walk, mild) != "",
           describe_alternative(long_walk, mild))

# Fewer changes is a comfort argument and is allowed to cost a few minutes.
two_hop = summarise_journey({"legs": [walk_leg(0, 5), train_leg(5, 15), train_leg(20, 15)]})
one_hop_slower = summarise_journey({"legs": [walk_leg(0, 5), train_leg(5, 40)]})
check_true("fewer changes is allowed to cost a little time",
           "fewer change" in describe_alternative(two_hop, one_hop_slower),
           describe_alternative(two_hop, one_hop_slower))

# Nothing arriving far later is pitched, whatever its merits.
way_later = summarise_journey({"legs": [walk_leg(60, 2), train_leg(62, 20)]})
check("nothing arriving far later is offered", describe_alternative(long_walk, way_later), "")


print("\n── format_journeys() ─────────────────────────────────")

text = format_journeys(rank_journeys([summarise_journey(direct), summarise_journey(two_trains)]),
                       " (from home)")
check_true("the origin is named", "(from home)" in text, text)
check_true("waiting is surfaced", "min waiting" in text, text)
check_true("live data is flagged", "live times" in text, text)
check_true("the walk legs are spelled out", "Walk" in text, text)
check_true("empty input does not crash", "No journeys" in format_journeys([]))

sched_text = format_journeys(rank_journeys([summarise_journey(sched)]))
check_true("a timetable-only journey is labelled", "timetable only" in sched_text, sched_text)

print("\n── _as_lonlat() ──────────────────────────────────────")

# resolve_origin returns "lat,lng" because that is the order the rest of this
# project uses; ORS wants [lon, lat]. Getting it backwards puts you in the
# Indian Ocean rather than erroring, which is why this is its own function.
check("lat,lng is flipped to [lon, lat]", _as_lonlat("-33.92,151.20"), [151.20, -33.92])
check("whitespace is tolerated", _as_lonlat("  -33.92 , 151.20 "), [151.20, -33.92])
check("positive coordinates work", _as_lonlat("51.5,-0.12"), [-0.12, 51.5])
check("an address is not coordinates", _as_lonlat("314 Gardeners Rd, Rosebery"), None)
check("empty is None", _as_lonlat(""), None)
check("out-of-range latitude is rejected", _as_lonlat("999,151.2"), None)
check("out-of-range longitude is rejected", _as_lonlat("-33.9,999"), None)


print("\n── _route_summary() ──────────────────────────────────")

ORS = {"features": [{"properties": {
    "summary": {"duration": 1380, "distance": 12400},
    "segments": [{"steps": [
        {"instruction": "Head north on Gardeners Road", "duration": 180},
        {"instruction": "Turn right onto Botany Road", "duration": 600},
        {"instruction": "Arrive at your destination", "duration": 0},
    ]}],
}}]}

text = _route_summary(ORS, "driving", " (from home)")
check_true("duration is in minutes", "23 min" in text, text)
check_true("distance is in km", "12.4 km" in text, text)
check_true("the origin is named", "(from home)" in text, text)
check_true("steps are listed", "Botany Road" in text, text)
check_true("a zero-duration step has no time", "Arrive at your destination\n" in text + "\n", text)

check("no features is handled", _route_summary({}, "driving"), "No route found.")
check("a feature with no summary is handled",
      _route_summary({"features": [{"properties": {}}]}, "driving"), "No route found.")

# Long routes get capped rather than flooding the model's context.
many = {"features": [{"properties": {
    "summary": {"duration": 600, "distance": 5000},
    "segments": [{"steps": [{"instruction": f"Step {i}", "duration": 60} for i in range(20)]}],
}}]}
capped = _route_summary(many, "cycling")
check_true("step lists are capped", "and 8 more steps" in capped, capped)


print()
if failures:
    print(f"✗ {len(failures)} failure(s):\n")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("✓ all travel tests passed")
