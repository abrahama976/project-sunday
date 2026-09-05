"""Tests for the trip-planning core in executors/travel_ops.py.

The ranking is the part that decides which route you are told to take, so it is
the part worth pinning. Everything under test here is pure — it takes an
already-decoded TfNSW response and returns numbers — so none of this needs a
network or an API key.

`_harness.setup()` supplies placeholder env values and stub modules for the
uninstalled third-party packages, so these are ordinary imports rather than
functions cut out of the source with `ast`. The stubs raise if a test ever
calls them, so nothing here can pass against a fake.

    python3 tests/test_travel.py
"""
import os
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(__file__))
from _harness import setup  # noqa: E402
setup()

from executors.travel_ops import (          # noqa: E402
    _parse_time, summarise_journey, rank_journeys, describe_alternative,
    format_journeys, _as_lonlat, _route_summary, leave_time_from,
    haversine_m, station_is_toward, add_access_leg, dedupe_journeys,
    verify_journeys, describe_strategy, _coord_pair, _route_minutes_km,
    _trip_params, park_ride_depart_at, headway_from_departures,
    choose_boarding_points, service_label, describe_frequency,
    format_services, as_efa_coord, _RAIL_CLASSES, PARK_RIDE_PARKING_MIN,
    parse_user_time, check_requested_time, is_real_stop_id, stop_display_name,
    drive_only_summary, promote_car_free, DRIVE_STRATEGIES, DROP_OFF_CLASSES,
)
from jobs import _stops_from_locations                        # noqa: E402
from executors.calendar_ops import is_placeholder_event_id   # noqa: E402
from jobs import travel_replan_due                            # noqa: E402

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

# Getting off a bus and back on the same route is not a change — TfNSW splits a
# through-service at a timing point, which produced "take the 358 to Sydenham,
# then take the 358 again". `changes` is a ranking key, so this was not merely
# cosmetic.
through = {"legs": [walk_leg(0, 5), train_leg(5, 20), train_leg(25, 15)]}
check("the same route with no gap is one vehicle, not a change",
      summarise_journey(through)["changes"], 0)

# But the route number alone does not settle it. All three of these are real
# changes to anyone actually making the journey.
waited = {"legs": [walk_leg(0, 5), train_leg(5, 20), train_leg(45, 15)]}
check("...the same route after a 20-minute wait is a change",
      summarise_journey(waited)["changes"], 1)

walked_between = {"legs": [walk_leg(0, 5), train_leg(5, 20),
                           walk_leg(25, 3, to="Other Stop"), train_leg(28, 15)]}
check("...and walking to another stop for the same route is a change",
      summarise_journey(walked_between)["changes"], 1)

unnamed = {"legs": [walk_leg(0, 5),
                    {"duration": 1200, "origin": {"name": "A", "departureTimePlanned": t(5)},
                     "destination": {"name": "B", "arrivalTimePlanned": t(25)},
                     "transportation": {"product": {"class": 1}}},
                    {"duration": 900, "origin": {"name": "B", "departureTimePlanned": t(25)},
                     "destination": {"name": "C", "arrivalTimePlanned": t(40)},
                     "transportation": {"product": {"class": 1}}}]}
check("an unnamed service counts as its own route, so changes are not undercounted",
      summarise_journey(unnamed)["changes"], 1)

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

# With a deadline, earliest arrival is the wrong question. The real one, from
# 2026-09-05: asked to reach Kogarah by 9:00 AM it chose the option leaving at
# 7:01 to arrive at 7:49, then reported a 48-minute journey and a two-hour-early
# departure in the same answer. 71 minutes on a platform, for no reason.
DEADLINE = BASE + timedelta(hours=2)                       # 10:00

# Both arrive in time; one leaves an hour and a half later.
crack_of_dawn = summarise_journey({"legs": [walk_leg(0, 5), train_leg(5, 25)]})    # 08:00 → 08:30
sensible = summarise_journey({"legs": [walk_leg(90, 5), train_leg(95, 25)]})       # 09:30 → 10:00

check("without a deadline, the earliest arrival still wins",
      rank_journeys([sensible, crack_of_dawn])[0]["arrive"], crack_of_dawn["arrive"])
check("with a deadline, the latest departure that makes it wins",
      rank_journeys([crack_of_dawn, sensible], DEADLINE)[0]["depart"],
      sensible["depart"])

# Latest ARRIVAL would not do. A slow journey can arrive later while leaving
# earlier, which is the same bug wearing a different hat.
slow_early = summarise_journey({"legs": [walk_leg(30, 5), train_leg(35, 85)]})     # 08:30 → 10:00
quick_late = summarise_journey({"legs": [walk_leg(80, 5), train_leg(85, 25)]})     # 09:20 → 09:50
check("a slow journey arriving later does not beat a later departure",
      rank_journeys([slow_early, quick_late], DEADLINE)[0]["depart"],
      quick_late["depart"])

# Ties still break on waiting, in both modes.
same_dep_waits = summarise_journey({"legs": [walk_leg(60, 5), train_leg(80, 20)]})   # 15 min wait
same_dep_brisk = summarise_journey({"legs": [walk_leg(60, 5), train_leg(65, 35)]})   # no wait
check("on an equal departure, less waiting still wins",
      rank_journeys([same_dep_waits, same_dep_brisk], DEADLINE)[0]["wait_min"], 0)

check("a deadline over an empty list is still empty", rank_journeys([], DEADLINE), [])


print("\n── driving the whole way ─────────────────────────────")

DRIVE = {"minutes": 19, "km": 10.4}

# Backwards from the deadline: the answer to "be there by 9" is a leave time.
by_ten = drive_only_summary(DRIVE, BASE, arrive_by=BASE + timedelta(hours=2))
check("a deadline sets the arrival", by_ten["arrive"], BASE + timedelta(hours=2))
check("...and the departure is the drive before it",
      by_ten["depart"], BASE + timedelta(hours=2) - timedelta(minutes=19))
check("a car journey has no waiting", by_ten["wait_min"], 0)
check("...and no changes", by_ten["changes"], 0)
check("...and no walking", by_ten["walk_min"], 0)
check("it is labelled as what it is", by_ten["strategy"], "drive_direct")

# A drive that would have to start in the past is not an option; it becomes a
# leave-now drive rather than a departure before the present moment.
too_late = drive_only_summary(DRIVE, BASE, arrive_by=BASE + timedelta(minutes=5))
check_true("a drive that cannot make the deadline still departs now, not earlier",
           too_late["depart"] >= BASE)

# Leaving now, forwards.
now_drive = drive_only_summary(DRIVE, BASE)
check("with no deadline it leaves now", now_drive["depart"], BASE)
check("...and arrives a drive later", now_drive["arrive"], BASE + timedelta(minutes=19))
check("no driving estimate means no option",
      drive_only_summary({"minutes": None}, BASE), None)
check("no drive at all means no option", drive_only_summary(None, BASE), None)


print("\n── keeping the car-free option visible ───────────────")

# Driving has no waiting and no changes, so it wins nearly every time a car is
# available — 10 minutes against 37 to Moore Park. Ranking it honestly is
# right; letting it be the only thing shown is not.
def tagged(strategy, minutes):
    j = summarise_journey({"legs": [walk_leg(0, 5), train_leg(5, minutes)]})
    j["strategy"] = strategy
    return j


drove = tagged("drive_direct", 10)
parked = tagged("park_ride", 20)
lifted = tagged("drop_off", 22)
bus = tagged("boarding", 40)

promoted = promote_car_free([drove, parked, lifted, bus])
check("the winner keeps its place on merit", promoted[0]["strategy"], "drive_direct")
check("...and the best car-free option is lifted to second",
      promoted[1]["strategy"], "boarding")
check("...without losing anything", len(promoted), 4)
check("...or reordering the rest",
      [j["strategy"] for j in promoted[2:]], ["park_ride", "drop_off"])

check("a car-free winner is left completely alone",
      promote_car_free([bus, drove])[0]["strategy"], "boarding")
check("...and its order is untouched",
      [j["strategy"] for j in promote_car_free([bus, drove])], ["boarding", "drive_direct"])
check("already second needs no promotion",
      [j["strategy"] for j in promote_car_free([drove, bus, parked])],
      ["drive_direct", "boarding", "park_ride"])
check("all-driven stays as ranked",
      [j["strategy"] for j in promote_car_free([drove, parked])],
      ["drive_direct", "park_ride"])
check("an empty list is unchanged", promote_car_free([]), [])

check_true("every drive strategy is accounted for",
           DRIVE_STRATEGIES == {"park_ride", "drop_off", "drive_direct"})
check_true("a drop-off can end at a bus stop, which parking cannot",
           5 in DROP_OFF_CLASSES and 5 not in _RAIL_CLASSES)


print("\n── naming the drive for what it is ───────────────────")

# "lift 6 min to X" was the first wording and said neither whose car it is nor
# what happens to it. The two options are not interchangeable and the label has
# to carry the difference.
def driven(strategy, drive_min):
    j = summarise_journey({"legs": [walk_leg(0, 2), train_leg(10, 25)]})
    j["strategy"] = strategy
    j["drive_min"] = drive_min
    return j


park_text = describe_strategy(driven("park_ride", 8))
drop_text = describe_strategy(driven("drop_off", 6))

check_true("park-and-ride says you park", "park" in park_text, park_text)
check_true("...and names the drive", "8 min" in park_text, park_text)
check_true("a drop-off says you were dropped off",
           "dropped off" in drop_text, drop_text)
check_true("...and never says you park",
           "park" not in drop_text, drop_text)
check_true("...and still names the drive", "6 min" in drop_text, drop_text)
check("driving the whole way says so",
      describe_strategy({"strategy": "drive_direct"}), "drive the whole way")


print("\n── describe_alternative() ────────────────────────────")

best = summarise_journey({"legs": [walk_leg(0, 5), train_leg(5, 20),
                                   train_leg(25, 15, line="T8")]})
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
two_hop = summarise_journey({"legs": [walk_leg(0, 5), train_leg(5, 15),
                                      train_leg(20, 15, line="T8")]})
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


print("\n── _trip_params() ────────────────────────────────────")

base = _trip_params("Home", "Work")
check("departure is the default macro", base["depArrMacro"], "dep")
check("...and the real origin is kept", base["name_origin"], "Home")
check("an arrival deadline flips the macro",
      _trip_params("Home", "Work", arrive_by=t(60))["depArrMacro"], "arr")

# A boarding-point search is the one that starts somewhere else, and says so.
check("a stop id is declared as a stop",
      _trip_params("10101", "Work", origin_type="stop")["type_origin"], "stop")


print("\n── a stop, or an address wearing a stop's clothes ────")

# The exact id production saved, ten times over, one per route.
REAL_COORD_PSEUDO_ID = "coord:4888949:3761579:GDAV:314 Gardeners Rd, Rosebery:0"

check("the id discovery actually saved is not a stop",
      is_real_stop_id(REAL_COORD_PSEUDO_ID), False)
check("a numeric global stop id is", is_real_stop_id("200060"), True)
check("...and one with a platform suffix is", is_real_stop_id("2000441:2"), True)

for pseudo in ("poiID:12:34", "streetID:99", "loc:abc", "address:1 Foo St"):
    check(f"{pseudo.split(':')[0]} is not a stop", is_real_stop_id(pseudo), False)

check("case does not rescue it", is_real_stop_id("COORD:1:2"), False)
check("nor does leading whitespace", is_real_stop_id("  coord:1:2"), False)
check("an empty id is not a stop", is_real_stop_id(""), False)
check("None is not a stop", is_real_stop_id(None), False)


print("\n── naming a stop ─────────────────────────────────────")

# What /v1/tp/coord actually returned on the first live run. All 158 stops came
# back with this as their name, and since stop_name is part of the upsert key,
# they collided into 21 rows under one name.
check("EFA's undefined placeholder is not a name",
      stop_display_name({"id": "201710", "name": "undefined, undefined"}),
      "201710")
check("...nor is a bare 'undefined'",
      stop_display_name({"id": "1", "name": "undefined"}), "1")
check("...nor blank, nor whitespace",
      stop_display_name({"id": "1", "name": "   "}), "1")

check("the short name is preferred",
      stop_display_name({"id": "1", "disassembledName": "Green Square Station",
                         "name": "Green Square Station, Botany Rd, Zetland"}),
      "Green Square Station")
check("...and the full name is used when there is no short one",
      stop_display_name({"id": "1", "name": "Green Square Station, Botany Rd"}),
      "Green Square Station, Botany Rd")
check("a placeholder short name falls through to the real full name",
      stop_display_name({"id": "1", "disassembledName": "undefined, undefined",
                         "name": "Lakes Hotel, Gardeners Rd"}),
      "Lakes Hotel, Gardeners Rd")

# Platforms and stop groups nest the name one level down.
check("a parent's name is used when the stop has none",
      stop_display_name({"id": "1", "name": "undefined, undefined",
                         "parent": {"name": "Central Station"}}),
      "Central Station")
check("properties are the last place looked",
      stop_display_name({"id": "1", "properties": {"STOP_NAME": "Mascot"}}),
      "Mascot")

# Falling back to the id rather than "" is the point: an id is unique, so the
# worst case is an ugly label instead of rows merging into one another.
check("with nothing at all, the id is the name",
      stop_display_name({"id": "G201868"}), "G201868")
check("with truly nothing, something printable", stop_display_name({}), "unnamed stop")

# And the whole reason this matters: two real stops must stay two rows.
two_stops = [
    {"id": "201710", "name": "undefined, undefined",
     "coord": [-33.9066, 151.2064], "productClasses": [1]},
    {"id": "202010", "name": "undefined, undefined",
     "coord": [-33.9150, 151.2000], "productClasses": [5]},
]
named = _stops_from_locations(two_stops, (-33.922863, 151.206547), 5000)
check("two unnamed stops keep two distinct names",
      len({s["name"] for s in named}), 2)


print("\n── _stops_from_locations() ───────────────────────────")

HOME = (-33.922863, 151.206547)          # 314 Gardeners Rd, as saved

# What stop_finder actually returned: the address, echoed back, and nothing
# else. Everything downstream was correct about a place you cannot board at.
address_only = [{
    "id": REAL_COORD_PSEUDO_ID,
    "name": "314 Gardeners Rd, Rosebery",
    "coord": [-33.922854, 151.206547],
    "productClasses": [5],
}]
check("the address-only response yields no stops",
      _stops_from_locations(address_only, HOME, 2000), [])

# A real one, mixed with the pseudo-location EFA likes to include.
mixed = [
    {"id": REAL_COORD_PSEUDO_ID, "name": "314 Gardeners Rd",
     "coord": [-33.922854, 151.206547], "productClasses": [5]},
    {"id": "2018130", "name": "Gardeners Rd at Rosebery",
     "coord": [-33.9235, 151.2050], "productClasses": [5]},
    {"id": "200070", "name": "Green Square Station",
     "coord": [-33.9070, 151.2010], "productClasses": [1]},
]
got = _stops_from_locations(mixed, HOME, 2000)
check("the pseudo-location is dropped and the real stops kept",
      [s["id"] for s in got], ["2018130", "200070"])
check("...nearest first",
      [s["name"] for s in got], ["Gardeners Rd at Rosebery", "Green Square Station"])
check_true("...with a real walking distance, not zero",
           got[0]["distance_m"] > 50)
check("...and product classes preserved, so rail is distinguishable",
      got[1]["classes"], {1})

# The radius still applies, and now it has something to apply to.
check("a stop beyond the radius is excluded",
      [s["id"] for s in _stops_from_locations(mixed, HOME, 300)], ["2018130"])
check("a location with no coordinate is skipped",
      _stops_from_locations([{"id": "200070", "name": "X"}], HOME, 2000), [])


print("\n── the time the user asked for ───────────────────────")

SYD = ZoneInfo("Australia/Sydney")

# The bug this exists for. A model asked for "tomorrow at 7am" writes
# 2026-09-05T07:00 with no offset. _parse_time calls that 07:00 UTC, which
# _trip_params then renders as 17:00 in Sydney — a trip planned, correctly and
# uselessly, for five in the afternoon.
naive = parse_user_time("2026-09-05T07:00")
check("a naive time is the user's wall clock, not UTC",
      naive.astimezone(SYD).strftime("%H:%M"), "07:00")
check("...and it reaches TfNSW as the hour that was asked for",
      _trip_params("Home", "Work", depart_at="2026-09-05T07:00")["itdTime"], "0700")
check("...on the right date",
      _trip_params("Home", "Work", depart_at="2026-09-05T07:00")["itdDate"], "20260905")

# An explicit offset is obeyed rather than overridden — the caller said what
# they meant, so the local-time default does not apply.
check("an explicit offset is left alone",
      parse_user_time("2026-09-05T07:00+00:00").astimezone(SYD).strftime("%H:%M"),
      "17:00")
check("a Z suffix is still UTC",
      parse_user_time("2026-09-05T07:00Z").astimezone(SYD).strftime("%H:%M"), "17:00")
check_true("nonsense parses to None", parse_user_time("next tuesday-ish") is None)
check_true("empty parses to None", parse_user_time("") is None)

# check_requested_time: pure, both boundaries pinned.
NOW = datetime(2026, 9, 4, 12, 0, tzinfo=SYD)


def refusal(arrive_by=None, depart_at=None, now=NOW):
    return check_requested_time(arrive_by, depart_at, now)[1]


check_true("a future arrival is accepted",
           refusal(arrive_by="2026-09-05T07:00") is None)
check_true("a future departure is accepted",
           refusal(depart_at="2026-09-04T18:00") is None)
check_true("no time at all is accepted",
           refusal() is None)

# The year the model invented before the prompt carried a date.
stale = refusal(arrive_by="2024-05-15T09:00")
check_true("a 2024 arrival is refused", stale is not None)
check_true("...and the refusal names the date it read, so the mistake is visible",
           "2024" in (stale or "") and "May" in (stale or ""))
check_true("...and says it is in the past", "already passed" in (stale or ""))

check_true("a departure earlier today is refused",
           refusal(depart_at="2026-09-04T08:00") is not None)

# Both sides of the boundary. "Already past" must mean strictly before now:
# a request for this exact minute is a request for now, not for the past.
check_true("exactly now is not past", refusal(depart_at=NOW.isoformat()) is None)
check_true("one minute ago is past",
           refusal(depart_at=(NOW - timedelta(minutes=1)).isoformat()) is not None)
check_true("one minute ahead is fine",
           refusal(depart_at=(NOW + timedelta(minutes=1)).isoformat()) is None)

# An unreadable time is refused, not silently dropped. Dropping arrive_by turns
# "get me there by 9" into "leave now" — which looks like an answer, and is not
# the one that was asked for.
bad = refusal(arrive_by="quarter past nine")
check_true("an unreadable time is refused", bad is not None)
check_true("...and is not reported as being in the past",
           "already passed" not in (bad or ""))
check_true("...and quotes what it could not read", "quarter past nine" in (bad or ""))

# The accepted case hands back parsed times, so callers need not re-parse.
times, err = check_requested_time("2026-09-05T07:00", None, NOW)
check_true("an accepted request returns its parsed times", err is None and times[0] is not None)
check("...as the local hour asked for",
      times[0].astimezone(SYD).strftime("%H:%M"), "07:00")


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

# A boarding-point option is named by its SERVICE. "an alternative stop" tells
# you nothing; "343 from Gardeners Rd" is how the trip is actually thought of.
boarding = dict(summarise_journey({"legs": [walk_leg(0, 4, to="Gardeners Rd"),
                                            train_leg(4, 26, line="343",
                                                      frm="Gardeners Rd")]}),
                strategy="boarding")
check("a boarding-point option is named by its route",
      describe_strategy(boarding), "343 from Gardeners Rd")

pr_labelled = dict(parked, strategy="park_ride")
check("park-and-ride names the drive and the station",
      describe_strategy(pr_labelled), "drive 20 min to Green Square and park, then transit")

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


print("\n── choose_boarding_points() — variety, not proximity ──")

def svc(route, stop, walk, headsign="", hidden=False, headway=None, source="discovered"):
    return {"route": route, "stop_name": stop, "walk_min": walk, "headsign": headsign,
            "is_hidden": hidden, "headway_min": headway, "source": source}

# The failure this whole mechanism exists to fix: a road served by one bus has
# many stops on it, and taking the five NEAREST would spend five queries
# rediscovering the journey the baseline already found.
one_route = [svc("343", f"Gardeners Rd stop {n}", n) for n in range(1, 6)]
picked = choose_boarding_points(one_route, 5)
check("five stops on one route collapse to one", len(picked), 1)
check("...and it is the nearest of them", picked[0]["stop_name"], "Gardeners Rd stop 1")

# The real local network: different routes going different places.
local = [
    svc("343", "Gardeners Rd", 4, "Central", headway=10),
    svc("358", "Gardeners Rd", 4, "Mascot", headway=15),
    svc("306", "Gardeners Rd", 6, "Sans Souci"),
    svc("M1",  "Waterloo Station", 19, "Sydenham", headway=5),
    svc("343", "Bourke St", 9, "Central"),          # same route, further away
]
picked = choose_boarding_points(local, 5)
check("one entry per distinct route", len(picked), 4)
check("nearest first", [p["route"] for p in picked][:2], ["343", "358"])
check("the far stop for a route already covered is dropped",
      [p["stop_name"] for p in picked if p["route"] == "343"], ["Gardeners Rd"])
check("the metro is included despite the longer walk",
      any(p["route"] == "M1" for p in picked), True)

check("the limit is honoured", len(choose_boarding_points(local, 2)), 2)
check("a hidden route is not offered",
      any(p["route"] == "306" for p in
          choose_boarding_points([svc("306", "Gardeners Rd", 6, hidden=True)], 5)), False)
check("a route with no walk time still counts, sorted last",
      [p["route"] for p in choose_boarding_points(
          [svc("999", "Far stop", None), svc("343", "Gardeners Rd", 4)], 5)],
      ["343", "999"])
check("nothing in, nothing out", choose_boarding_points([], 5), [])
check("None in, nothing out", choose_boarding_points(None, 5), [])


print("\n── headway_from_departures() ─────────────────────────")

def at(*minutes):
    return [BASE + timedelta(minutes=m) for m in minutes]

check("an even ten-minute service reads as 10",
      headway_from_departures(at(0, 10, 20, 30)), 10)
check("departures out of order are still sorted",
      headway_from_departures(at(20, 0, 10)), 10)

# The median, not the mean: one long gap across a timetable break would drag an
# average to a number no service actually runs at.
check("one long gap does not distort the figure",
      headway_from_departures(at(0, 10, 20, 90)), 10)

check("a single departure gives no frequency",
      headway_from_departures(at(5)), None)
check("no departures give no frequency", headway_from_departures([]), None)
check("None gives no frequency", headway_from_departures(None), None)
check("duplicate timestamps do not read as a zero-minute service",
      headway_from_departures(at(0, 0)), None)


print("\n── service_label() / describe_frequency() ────────────")

check("the first vehicle leg names the service",
      service_label(summarise_journey({"legs": [walk_leg(0, 4, to="Gardeners Rd"),
                                                train_leg(4, 26, line="343",
                                                          frm="Gardeners Rd")]})),
      "343 from Gardeners Rd")
check("a drive to the station is not the service",
      service_label(add_access_leg(
          summarise_journey({"legs": [train_leg(30, 20, line="T8", frm="Green Square")]}),
          15, mode="Drive")),
      "T8 from Green Square")
check("no vehicle leg means no service", service_label({"legs": []}), "")

check("a known frequency is stated", describe_frequency({"headway_min": 10}), "every ~10 min")
# Silent rather than guessing: a wrong headway gets read as fact and changes
# when someone leaves the house.
check("an unknown frequency says nothing", describe_frequency({}), "")
check("a nonsense frequency says nothing", describe_frequency({"headway_min": 0}), "")


print("\n── the car is for once in a while ────────────────────")

NOW3 = BASE - timedelta(minutes=5)
transit_opt = summarise_journey({"legs": [train_leg(0, 40)]})           # 40 min
quick_pr = add_access_leg(summarise_journey({"legs": [train_leg(10, 10)]}), 5, mode="Drive")
slow_pr = add_access_leg(summarise_journey({"legs": [train_leg(10, 30)]}), 5, mode="Drive")
exact_pr = add_access_leg(summarise_journey({"legs": [train_leg(10, 25)]}), 5, mode="Drive")

# 35 min against a 40 min transit option: a five-minute saving does not justify
# getting the car out when the bar is ten.
check("park-and-ride that barely wins is not worth the car",
      len(verify_journeys([transit_opt, slow_pr], NOW3, None, None, 10)), 1)
# Exactly the margin clears it — the bar is "at least this much", not "more".
check("a saving of exactly the margin does clear the bar",
      len(verify_journeys([transit_opt, exact_pr], NOW3, None, None, 10)), 2)
check("park-and-ride that clearly wins is kept",
      len(verify_journeys([transit_opt, quick_pr], NOW3, None, None, 10)), 2)
check("with no margin set it is left alone",
      len(verify_journeys([transit_opt, slow_pr], NOW3, None, None, 0)), 2)
# With nothing car-free to compare against, it is the only option there is.
check("park-and-ride alone still stands",
      len(verify_journeys([slow_pr], NOW3, None, None, 10)), 1)


print("\n── format_services() ─────────────────────────────────")

listing = format_services(local, "home")
check_true("stops are named", "Gardeners Rd (4 min walk)" in listing, listing)
check_true("routes carry their destination", "343 to Central" in listing, listing)
check_true("...and their frequency", "every ~10 min" in listing, listing)
check_true("a route without a frequency simply omits it",
           "306 to Sans Souci" in listing and "306 to Sans Souci ·" not in listing, listing)
check_true("your own corrections are marked",
           "yours" in format_services([svc("X99", "My stop", 3, "Somewhere",
                                           source="user")], "home"))
check_true("an empty inventory says so rather than implying nothing runs",
           "don't know what runs near" in format_services([], "home"))

print("\n── as_efa_coord() / coordinate trip params ───────────")

# EFA is the one thing here that wants longitude first. Getting it backwards
# does not error — it plans from the Indian Ocean and returns nothing, which
# reads exactly like "no services run". That is the bug that made every trip
# this project ever planned come back empty.
check("longitude comes first, latitude second",
      as_efa_coord((-33.9068, 151.2010)), "151.201:-33.9068:EPSG:4326")
check("a Central-ish coordinate round-trips",
      as_efa_coord((-33.8832, 151.2065)), "151.2065:-33.8832:EPSG:4326")

coord_params = _trip_params(as_efa_coord((-33.9068, 151.201)),
                            as_efa_coord((-33.9900, 151.1300)),
                            origin_type="coord", destination_type="coord")
check("both ends are declared as coordinates",
      (coord_params["type_origin"], coord_params["type_destination"]),
      ("coord", "coord"))
check("the origin is sent as lon:lat",
      coord_params["name_origin"], "151.201:-33.9068:EPSG:4326")

# A boarding point is a stop id, so it stays a stop — but the destination is
# still the resolved coordinate.
mixed = _trip_params("2000123", as_efa_coord((-33.99, 151.13)),
                     origin_type="stop", destination_type="coord")
check("a boarding point stays a stop id", mixed["type_origin"], "stop")
check("...while the destination stays a coordinate", mixed["type_destination"], "coord")


print("\n── is_placeholder_event_id() (calendar_ops) ──────────")

# Lives in calendar_ops but is pure and guards the approval queue, so it is
# pinned here rather than left untested for being in another file.
# The one that actually reached the approval queue and 404'd after approval.
check_true("the id that failed in production is caught",
           is_placeholder_event_id("Primary_xxxxxxxxxxxxxxxxxx"))
check_true("an angle-bracket placeholder is caught",
           is_placeholder_event_id("<event_id>"))
check_true("the bare parameter name is caught", is_placeholder_event_id("event_id"))
check_true("an empty id is caught", is_placeholder_event_id(""))
check_true("whitespace is caught", is_placeholder_event_id("   "))
check_true("None is caught", is_placeholder_event_id(None))
check_true("'your_event_here' is caught", is_placeholder_event_id("your_event_here"))

# Real Google event ids are opaque base32hex-ish strings. None of these may be
# rejected, or the guard breaks the feature it is protecting.
for real in ("4f8s0nk3q1p2r5t7v9x0y2z4a6",
             "_60q30c1g60o30e1i60o4ac1g60rj8gpl88rj2c1h84s34h9g60s30c1g60o30c1g",
             "abc123XYZ"):
    check_true(f"a real id is accepted: {real[:18]}…",
               not is_placeholder_event_id(real))

print("\n── the harness itself ────────────────────────────────")

# The stubs exist to satisfy imports, never to answer questions. A stub that
# quietly returned something plausible would be worse than having no tests: it
# would look like coverage while testing a fake. So prove they refuse.
import httpx                                    # noqa: E402
import supabase                                 # noqa: E402
from _harness import TestReachedRealIO          # noqa: E402

for label, call in (
    ("httpx.AsyncClient", lambda: httpx.AsyncClient()),
    ("supabase.create_client", lambda: supabase.create_client("u", "k")),
):
    try:
        call()
    except TestReachedRealIO:
        print(f"  ok  {label} refuses to run in a test")
    except Exception as exc:                    # noqa: BLE001
        failures.append(f"{label} raised {type(exc).__name__}, not TestReachedRealIO")
    else:
        failures.append(f"{label} SILENTLY SUCCEEDED — a test could pass against a fake")
print()
if failures:
    print(f"✗ {len(failures)} failure(s):\n")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("✓ all travel tests passed")
