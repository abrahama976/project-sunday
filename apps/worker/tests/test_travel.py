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
    "_as_lonlat", "_route_summary", "leave_time_from",
    # The search core added with the multi-strategy planner.
    "haversine_m", "station_is_toward", "add_access_leg", "dedupe_journeys",
    "verify_journeys", "describe_strategy", "_exclude_params", "_coord_pair",
    "_route_minutes_km", "_trip_params", "park_ride_depart_at",
}
_keep = [
    n for n in _tree.body
    if (isinstance(n, ast.FunctionDef) and n.name in _WANTED)
    or (isinstance(n, ast.Assign)
        and getattr(n.targets[0], "id", "") in {"_WALK_CLASSES", "_MODE_NAMES",
                                                "_ALT_MAX_LATER_MIN", "_COORD_PAIR",
                                                "_ORS_PROFILES", "_RAIL_CLASSES",
                                                "_BUS_CLASSES", "MAX_ACCESS_WALK_M",
                                                "PARK_RIDE_MAX_CANDIDATES",
                                                "PARK_RIDE_MAX_DRIVE_MIN",
                                                "PARK_RIDE_PARKING_MIN"})
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
leave_time_from = _g["leave_time_from"]
haversine_m = _g["haversine_m"]
station_is_toward = _g["station_is_toward"]
add_access_leg = _g["add_access_leg"]
dedupe_journeys = _g["dedupe_journeys"]
verify_journeys = _g["verify_journeys"]
describe_strategy = _g["describe_strategy"]
_exclude_params = _g["_exclude_params"]
_coord_pair = _g["_coord_pair"]
_route_minutes_km = _g["_route_minutes_km"]
_trip_params = _g["_trip_params"]
park_ride_depart_at = _g["park_ride_depart_at"]
_RAIL_CLASSES = _g["_RAIL_CLASSES"]
_BUS_CLASSES = _g["_BUS_CLASSES"]
PARK_RIDE_PARKING_MIN = _g["PARK_RIDE_PARKING_MIN"]

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


print("\n── leave_time_from() ─────────────────────────────────")

# The number an alert fires on. Five minutes wrong here is the whole ball game,
# which is why it is pure and tested rather than buried in the job.
journeys = rank_journeys([summarise_journey(direct)])          # departs 08:00
check("the buffer is subtracted from the first departure",
      leave_time_from(journeys, 5).astimezone(SYD).strftime("%H:%M"), "07:55")
check("a zero buffer leaves the departure alone",
      leave_time_from(journeys, 0).astimezone(SYD).strftime("%H:%M"), "08:00")
check("a bigger buffer leaves earlier",
      leave_time_from(journeys, 15).astimezone(SYD).strftime("%H:%M"), "07:45")

# A negative buffer would tell you to leave AFTER the train goes.
check("a negative buffer is clamped, not honoured",
      leave_time_from(journeys, -10).astimezone(SYD).strftime("%H:%M"), "08:00")

check_true("no journeys means no leave time", leave_time_from([], 5) is None)

# It reads the FIRST journey, which rank_journeys has already put best-first.
two = rank_journeys([summarise_journey({"legs": [walk_leg(30, 5), train_leg(35, 20)]}),
                     summarise_journey(direct)])
check("it uses the best-ranked journey, not the first supplied",
      leave_time_from(two, 5).astimezone(SYD).strftime("%H:%M"), "07:55")


print("\n── haversine_m() / station_is_toward() ───────────────")

CENTRAL = (-33.8832, 151.2065)
GREEN_SQ = (-33.9068, 151.2010)
PARRAMATTA = (-33.8170, 151.0050)

# Roughly 2.7 km between Central and Green Square. Loose bounds on purpose:
# this only ever decides whether a candidate is worth a request.
d = haversine_m(CENTRAL, GREEN_SQ)
check_true("Central to Green Square is a couple of km", 2000 < d < 3500, f"got {d:.0f} m")
check("the same point is zero distance", round(haversine_m(CENTRAL, CENTRAL)), 0)
check_true("distance is symmetric",
           abs(haversine_m(CENTRAL, GREEN_SQ) - haversine_m(GREEN_SQ, CENTRAL)) < 1)

# Heading from Green Square to Central: Central is toward it, Parramatta is not.
check_true("a station on the way counts as toward",
           station_is_toward(GREEN_SQ, CENTRAL, CENTRAL))
check_true("a station in the wrong direction does not",
           not station_is_toward(GREEN_SQ, PARRAMATTA, CENTRAL))
check_true("missing coordinates are not toward anything",
           not station_is_toward(None, CENTRAL, CENTRAL))


print("\n── _coord_pair() ─────────────────────────────────────")

check("a normal (lat, lng) pair passes through", _coord_pair([-33.9, 151.2]), (-33.9, 151.2))
# A swapped pair does not raise — it silently relocates the station, so it is
# corrected rather than trusted.
check("a swapped pair is put back the right way", _coord_pair([151.2, -33.9]), (-33.9, 151.2))
check_true("a short list is rejected", _coord_pair([151.2]) is None)
check_true("nonsense is rejected", _coord_pair(["a", "b"]) is None)
check_true("an out-of-range pair is rejected", _coord_pair([200.0, 300.0]) is None)


print("\n── _exclude_params() / _trip_params() ────────────────")

check("no exclusion means no exclusion keys", _exclude_params(None), {})
check("excluding rail sets a flag per class",
      _exclude_params({1, 2}), {"excludedMeans": "checkbox", "exclMOT_1": 1, "exclMOT_2": 1})

base = _trip_params("Home", "Work")
check("a plain search excludes nothing", "excludedMeans" in base, False)
check("departure is the default macro", base["depArrMacro"], "dep")
check("an arrival deadline flips the macro",
      _trip_params("Home", "Work", arrive_by=t(60))["depArrMacro"], "arr")

biased = _trip_params("Home", "Work", exclude=_RAIL_CLASSES)
check("the bus-biased search excludes rail", biased["exclMOT_1"], 1)
check("...and keeps the real origin", biased["name_origin"], "Home")

# Park-and-ride is the one search that starts somewhere else, and it says so.
check("a stop id is declared as a stop",
      _trip_params("10101", "Work", origin_type="stop")["type_origin"], "stop")


print("\n── add_access_leg() — the arithmetic that keeps it honest ──")

# As TfNSW returns it: the journey begins on the platform. The drive to reach
# that platform is simply not in the response.
from_station = summarise_journey({"legs": [train_leg(30, 20, frm="Green Square")]})
check("TfNSW's own answer starts at the platform",
      from_station["depart"].astimezone(SYD).strftime("%H:%M"), "08:30")

parked = add_access_leg(from_station, 20, mode="Drive")
check("departure moves earlier by the access time",
      parked["depart"].astimezone(SYD).strftime("%H:%M"), "08:10")
check("duration grows by the same amount", parked["duration_min"], from_station["duration_min"] + 20)
check("arrival is untouched", parked["arrive"], from_station["arrive"])
check("waiting is untouched — access is moving time",
      parked["wait_min"], from_station["wait_min"])
check("the access leg is prepended", parked["legs"][0]["mode"], "Drive")
check("...and carries its own duration", parked["legs"][0]["minutes"], 20)
check("...and points at the boarding stop", parked["legs"][0]["to"], "Green Square")
check("a drive is credited as driving, not walking", parked.get("drive_min"), 20)
check("walking is left alone by a drive", parked["walk_min"], from_station["walk_min"])

walked = add_access_leg(from_station, 12, mode="Walk")
check("a walk is credited as walking", walked["walk_min"], from_station["walk_min"] + 12)
check_true("a walk adds no drive time", walked.get("drive_min") is None)

# The caller still wants the original to compare against.
check("the input is not mutated",
      from_station["depart"].astimezone(SYD).strftime("%H:%M"), "08:30")
check("a zero access leg changes nothing", add_access_leg(from_station, 0), from_station)


print("\n── park_ride_depart_at() ─────────────────────────────")

# TfNSW is asked for trips FROM the station and knows nothing about the drive.
# Without this shift it offers a train that leaves before you could arrive —
# verify_journeys then throws it away, so park-and-ride would never appear at
# all on a "how do I get there now" question.
check("the requested departure is pushed back by the drive",
      park_ride_depart_at(None, 20, BASE)[11:16], "08:20")
check("an explicit departure time is shifted too",
      park_ride_depart_at(t(30), 20, BASE)[11:16], "08:50")
check("no drive means no shift", park_ride_depart_at(None, 0, BASE)[11:16], "08:00")
check("a negative access time cannot move it earlier",
      park_ride_depart_at(None, -10, BASE)[11:16], "08:00")
check("an unparseable time falls back to now",
      park_ride_depart_at("not a time", 15, BASE)[11:16], "08:15")

print("\n── the trap: an option that wins only by hiding its access leg ──")

# Two ways to the same place, both arriving 08:50.
#   A — walk to the local stop and ride:        leave 08:20, 30 min
#   B — a faster service from a station:        leave 08:30, 20 min
# B looks better, and would be chosen, until the 20 minutes it takes to drive
# and park at that station are counted.
local = summarise_journey({"legs": [walk_leg(20, 5), train_leg(25, 25)]})
station = summarise_journey({"legs": [train_leg(30, 20, frm="Green Square")]})

naive = rank_journeys([local, station])
check("without its drive leg the station option wins", naive[0]["duration_min"], 20)
check("...and would tell you to leave at 08:25",
      leave_time_from(naive, 5).astimezone(SYD).strftime("%H:%M"), "08:25")

honest = rank_journeys([local, add_access_leg(station, 20, mode="Drive")])
check("with the drive counted, the local option wins", honest[0]["duration_min"], 30)
check("...and the leave time is one you can actually meet",
      leave_time_from(honest, 5).astimezone(SYD).strftime("%H:%M"), "08:15")


print("\n── dedupe_journeys() ─────────────────────────────────")

# The bus-biased and rail-biased searches rediscover what the baseline found.
a = summarise_journey({"legs": [walk_leg(0, 8), train_leg(8, 30)]})
b = summarise_journey({"legs": [walk_leg(0, 8), train_leg(8, 30)]})
different = summarise_journey({"legs": [walk_leg(0, 8), train_leg(20, 30, line="T8")]})

check("the same service twice collapses to one", len(dedupe_journeys([a, b])), 1)
check("a genuinely different service survives", len(dedupe_journeys([a, different])), 2)
check("the first copy is the one kept", dedupe_journeys([a, b])[0] is a, True)
check("empties are dropped", len(dedupe_journeys([None, a])), 1)


print("\n── verify_journeys() — calculate and verify ──────────")

NOW = BASE + timedelta(minutes=15)          # 08:15
gone = summarise_journey({"legs": [train_leg(0, 30)]})        # left 08:00
upcoming = summarise_journey({"legs": [train_leg(30, 20)]})   # leaves 08:30

check("a departure already in the past is dropped",
      len(verify_journeys([gone], NOW)), 0)
check("an upcoming departure is kept", len(verify_journeys([upcoming], NOW)), 1)

deadline = BASE + timedelta(minutes=45)     # 08:45
check("an arrival after the deadline is dropped",
      len(verify_journeys([upcoming], NOW, deadline)), 0)
check("an arrival before it is kept",
      len(verify_journeys([upcoming], NOW, BASE + timedelta(minutes=60))), 1)

# Park-and-ride that loses to simply driving the whole way is not a plan.
pr = add_access_leg(summarise_journey({"legs": [train_leg(40, 20)]}), 15, mode="Drive")
check("park-and-ride slower than driving is dropped",
      len(verify_journeys([pr], NOW, None, 20)), 0)
check("park-and-ride faster than driving is kept",
      len(verify_journeys([pr], NOW, None, 90)), 1)
check("without a driving figure it is left alone",
      len(verify_journeys([pr], NOW, None, None)), 1)
check("a journey with no usable times is dropped", len(verify_journeys([None], NOW)), 0)


print("\n── describe_strategy() / _route_minutes_km() ─────────")

check("the baseline needs no explanation", describe_strategy({"strategy": "baseline"}), "")
check("the bus search says why", describe_strategy({"strategy": "bus"}), "bus only — no station walk")
check("the rail search says why", describe_strategy({"strategy": "rail"}), "via a station")

pr_labelled = dict(parked, strategy="park_ride")
check("park-and-ride names the drive and the station",
      describe_strategy(pr_labelled), "drive 20 min to Green Square, then transit")

check("an ORS route yields minutes and km",
      _route_minutes_km({"features": [{"properties": {"summary":
                                       {"duration": 1200, "distance": 8400}}}]}),
      (20, 8.4))
check("an empty ORS response yields nothing", _route_minutes_km({}), (None, None))
check("a route without a summary yields nothing",
      _route_minutes_km({"features": [{"properties": {}}]}), (None, None))


print("\n── format_journeys() with a driving comparison ───────")

out = format_journeys([local], drive={"minutes": 18, "km": 9.2})
check_true("the driving line is always shown", "Driving: 18 min, 9.2 km" in out, out)
check_true("...and says how it compares", "12 min faster than transit" in out, out)

slower = format_journeys([local], drive={"minutes": 55, "km": 30.0})
check_true("a slower drive is named as slower", "25 min slower than transit" in slower, slower)

parked_out = format_journeys([dict(parked, strategy="park_ride")])
check_true("a drive leg is rendered as driving", "Drive 20 min to Green Square" in parked_out,
           parked_out)
check_true("parking is not silently assumed",
           "Parking availability is not checked" in parked_out, parked_out)



print("\n── travel_replan_due() (jobs.py) ─────────────────────")

# Lives in jobs.py but is travel arithmetic, and it decides how much of the
# day's TfNSW traffic exists — so it is pinned here with the rest of the
# planning logic rather than left untested for being in the wrong file.
_JOBS = open(os.path.join(os.path.dirname(__file__), "..", "jobs.py")).read()
_jt = ast.parse(_JOBS)
_jkeep = [
    n for n in _jt.body
    if (isinstance(n, ast.FunctionDef) and n.name == "travel_replan_due")
    or (isinstance(n, ast.Assign)
        and getattr(n.targets[0], "id", "") in {"TRAVEL_REPLAN_LEAD_MINUTES",
                                                "TRAVEL_REPLAN_MIN_INTERVAL_MINUTES"})
]
_jg = {"timedelta": timedelta, "__name__": "pure"}
exec(compile(ast.Module(body=_jkeep, type_ignores=[]), "jobs.py", "exec"), _jg)
travel_replan_due = _jg["travel_replan_due"]

NOW2 = BASE                                      # 08:00
soon = BASE + timedelta(minutes=15)              # inside the 20-min lead window
far = BASE + timedelta(hours=4)                  # a long way off

check_true("an event never planned is planned now",
           travel_replan_due(None, None, NOW2))
check_true("a row with no leave time is planned now",
           travel_replan_due(BASE - timedelta(minutes=1), None, NOW2))

# Close to the leave time, cheapness stops mattering: this is the window where
# a late train can still change what you do.
check_true("close to the leave time it re-plans every tick",
           travel_replan_due(NOW2 - timedelta(minutes=1), soon, NOW2))

# Hours out, a fresh plan is not worth a search. This is the fix: an event four
# hours away used to cost a full search every five minutes.
check_true("a fresh plan for a distant event is not redone",
           not travel_replan_due(NOW2 - timedelta(minutes=5), far, NOW2))
check_true("...but a stale one is",
           travel_replan_due(NOW2 - timedelta(minutes=45), far, NOW2))
check_true("the staleness boundary re-plans",
           travel_replan_due(NOW2 - timedelta(minutes=30), far, NOW2))

# A leave time that has already slipped past is still inside the window, so it
# keeps re-planning rather than freezing on a stale answer.
check_true("an overdue leave time still re-plans",
           travel_replan_due(NOW2, BASE - timedelta(minutes=5), NOW2))

print()
if failures:
    print(f"✗ {len(failures)} failure(s):\n")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("✓ all travel tests passed")
