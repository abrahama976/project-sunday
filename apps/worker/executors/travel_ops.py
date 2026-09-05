import asyncio
import httpx
import json
import re
from config import (OPENROUTESERVICE_API_KEY, TFNSW_API_KEY, TRAVEL_BUFFER_MINUTES,
                    BOARDING_POINT_LIMIT, PARK_RIDE_MIN_SAVING_MIN, PARK_RIDE_RADIUS_M,
                    USER_TIMEZONE)
from utils import resolve_origin
from travel.contracts import ResolvedPlace, NOT_FOUND
from travel.resolve import candidate_from_location, choose_place, saved_place_match
from travel.gate import gate_journeys, rejection_summary

# ── Driving, walking, cycling (OpenRouteService) ────────────────────────────
# Was Google Maps. The Directions API returns REQUEST_DENIED without a billing
# account attached to the Cloud project — which this project will not have, and
# which had been failing silently in calendar_prep as well as in chat. ORS is
# key-only, 2000 directions/day, and 403s at the cap instead of billing.
#
# The one real difference: ORS routes between COORDINATES, where Google would
# accept a street address. So an address has to be geocoded first, which is a
# second call and a second thing that can fail.

ORS_BASE = "https://api.openrouteservice.org"
ORS_TIMEOUT = 20.0

# Sunday's modes → ORS profiles. Transit is deliberately absent: ORS does not
# do public transport, and pretending otherwise would silently return a walking
# route for a train journey.
_ORS_PROFILES = {
    "driving": "driving-car",
    "car": "driving-car",
    "walking": "foot-walking",
    "foot": "foot-walking",
    "cycling": "cycling-regular",
    "bicycling": "cycling-regular",
    "bike": "cycling-regular",
}

_COORD_PAIR = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")


def _as_lonlat(text: str):
    """"lat,lng" → (lon, lat) for ORS, which wants them the other way round.

    resolve_origin hands back "lat,lng" because that is the order everything
    else in this project uses. Getting this backwards puts you in the Indian
    Ocean rather than failing, so it is worth its own function and its own test.
    """
    match = _COORD_PAIR.match(text or "")
    if not match:
        return None
    lat, lon = float(match.group(1)), float(match.group(2))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return [lon, lat]


def _route_summary(data: dict, mode: str, origin_note: str = "") -> str:
    """Format an ORS directions response. Pure, so it can be tested."""
    features = data.get("features") or []
    if not features:
        return "No route found."

    props = features[0].get("properties") or {}
    summary = props.get("summary") or {}
    seconds = summary.get("duration")
    metres = summary.get("distance")
    if seconds is None or metres is None:
        return "No route found."

    minutes = int(round(seconds / 60))
    km = metres / 1000
    out = [f"{mode.capitalize()}{origin_note}: {minutes} min, {km:.1f} km"]

    steps = []
    for segment in props.get("segments") or []:
        steps.extend(segment.get("steps") or [])
    for step in steps[:12]:
        instruction = (step.get("instruction") or "").strip()
        if not instruction:
            continue
        step_min = int(round((step.get("duration") or 0) / 60))
        out.append(f"  · {instruction}" + (f" ({step_min} min)" if step_min else ""))
    if len(steps) > 12:
        out.append(f"  · …and {len(steps) - 12} more steps")

    return "\n".join(out)


async def _ors_geocode(http, text: str):
    """Address → [lon, lat] via ORS geocoding, or None."""
    res = await http.get(
        f"{ORS_BASE}/geocode/search",
        params={"api_key": OPENROUTESERVICE_API_KEY, "text": text,
                "boundary.country": "AU", "size": 1},
        timeout=ORS_TIMEOUT,
    )
    res.raise_for_status()
    features = (res.json() or {}).get("features") or []
    if not features:
        return None
    return (features[0].get("geometry") or {}).get("coordinates")


async def travel_directions(
    destination: str,
    origin: str | None = None,
    mode: str = "driving",
    client=None,
    user_id: str | None = None,
) -> str:
    """Driving, walking or cycling directions via OpenRouteService.

    `origin` is optional: left out it resolves to the live position when the
    phone has reported recently, else the default saved place.

    Public transport is NOT handled here — see trip_plan, which has live TfNSW
    data and ranks alternatives. Asking for transit returns a pointer to it
    rather than a walking route in disguise.
    """
    if mode and mode.lower() in {"transit", "public_transport", "pt"}:
        return ("travel_directions does not do public transport. "
                "Use trip_plan for transit journeys — it has live TfNSW times.")

    profile = _ORS_PROFILES.get((mode or "driving").lower())
    if not profile:
        return (f"Unknown travel mode '{mode}'. "
                f"Use one of: {', '.join(sorted(set(_ORS_PROFILES)))}.")

    if not OPENROUTESERVICE_API_KEY:
        return ("Error: OPENROUTESERVICE_API_KEY is not set. Get a free key at "
                "openrouteservice.org/dev/#/signup and put it in apps/worker/.env.")

    origin_note = ""
    if not origin:
        if client is None or not user_id:
            return "Error: no origin given and no user context to look one up."
        resolved = await resolve_origin(client, user_id)
        if not resolved:
            return ("I don't know where you're starting from — no recent location "
                    "and no default saved place. Add one under Settings → Places, "
                    "or tell me the starting point.")
        origin = resolved["origin"]
        origin_note = f" (from {resolved['source']})"

    # `http`, not `client`: `client` is the Supabase handle this function takes.
    async with httpx.AsyncClient() as http:
        try:
            start = _as_lonlat(origin) or await _ors_geocode(http, origin)
            end = _as_lonlat(destination) or await _ors_geocode(http, destination)
        except Exception as e:
            return f"Error looking up those locations: {e}"

        if not start:
            return f"I couldn't find '{origin}' on the map."
        if not end:
            return f"I couldn't find '{destination}' on the map."

        try:
            res = await http.post(
                f"{ORS_BASE}/v2/directions/{profile}/geojson",
                headers={"Authorization": OPENROUTESERVICE_API_KEY,
                         "Content-Type": "application/json"},
                json={"coordinates": [start, end]},
                timeout=ORS_TIMEOUT,
            )
            if res.status_code == 403:
                return ("OpenRouteService daily limit reached (2000 requests). "
                        "It resets 24 hours after the first request of the day.")
            res.raise_for_status()
            data = res.json()
        except Exception as e:
            return f"Error fetching directions: {e}"

    return _route_summary(data, mode, origin_note)


async def transit_departures(stop_keyword: str) -> str:
    """Get live departures from TfNSW Trip Planner API."""
    if not TFNSW_API_KEY:
        return "Error: TFNSW_API_KEY is not set."
        
    headers = {
        "Authorization": f"apikey {TFNSW_API_KEY}",
        "Accept": "application/json"
    }
    
    async with httpx.AsyncClient() as client:
        try:
            # Step 1: Find the stop ID
            finder_url = "https://api.transport.nsw.gov.au/v1/tp/stop_finder"
            finder_params = {
                "outputFormat": "rapidJSON",
                "type_sf": "any",
                "name_sf": stop_keyword,
                "coordOutputFormat": "EPSG:4326",
                "TfNSWSF": "true",
                "version": "10.2.1.42"
            }
            
            finder_res = await client.get(finder_url, headers=headers, params=finder_params)
            finder_res.raise_for_status()
            finder_data = finder_res.json()
            
            locations = finder_data.get("locations", [])
            if not locations:
                return f"No stops found for keyword '{stop_keyword}'."
                
            # Grab the best match
            stop = locations[0]
            stop_id = stop["id"]
            stop_name = stop["name"]
            
            # Step 2: Get departure monitor
            dep_url = "https://api.transport.nsw.gov.au/v1/tp/departure_mon"
            dep_params = {
                "outputFormat": "rapidJSON",
                "coordOutputFormat": "EPSG:4326",
                "mode": "direct",
                "type_dm": "stop",
                "name_dm": stop_id,
                "departureMonitorMacro": "true",
                "TfNSWDM": "true",
                "version": "10.2.1.42"
            }
            
            dep_res = await client.get(dep_url, headers=headers, params=dep_params)
            dep_res.raise_for_status()
            dep_data = dep_res.json()
            
        except Exception as e:
            return f"Error fetching TfNSW data: {e}"

    stop_events = dep_data.get("stopEvents", [])
    if not stop_events:
        return f"No upcoming departures found for {stop_name}."
        
    output = [f"Live Departures for {stop_name}:"]
    
    for idx, event in enumerate(stop_events[:5]):
        transportation = event.get("transportation", {})
        dest = transportation.get("destination", {"name": "Unknown"}).get("name")
        mode = transportation.get("product", {"class": 0}).get("class") # 1=Train, 5=Bus, 4=Light Rail, 9=Ferry
        mode_str = "Train" if mode == 1 else "Bus" if mode == 5 else "Light Rail" if mode == 4 else "Ferry" if mode == 9 else "Service"
        
        # Real-time departure if available, otherwise scheduled.
        # Parsed with the module's own `_parse_time` rather than dateutil:
        # dateutil was imported here but never declared in requirements.txt —
        # it arrives transitively today, and this line breaks the moment
        # whatever drags it in stops doing so. It also raises on a malformed
        # timestamp, where _parse_time returns None and the row degrades to
        # "Unknown time" instead of taking the whole departure board down.
        from zoneinfo import ZoneInfo
        dt = _parse_time(event.get("departureTimeEstimated")
                         or event.get("departureTimePlanned"))
        time_str = dt.astimezone(ZoneInfo("Australia/Sydney")).strftime("%-I:%M %p") if dt else "Unknown time"
            
        platform = event.get("location", {}).get("properties", {}).get("platform", "")
        platform_str = f" (Plat {platform})" if platform else ""
        
        output.append(f"- {time_str}: {mode_str} to {dest}{platform_str}")
        
    return "\n".join(output)


# ── Trip planning (TfNSW) ───────────────────────────────────────────────────
# The departure monitor above answers "what leaves this stop soon". This
# answers "how do I get there", which is a different endpoint on the same API
# and the one that carries whole journeys with per-leg real-time data.
#
# Everything below the IO wrapper is pure: it takes an already-decoded TfNSW
# response and returns numbers. That is deliberate — the ranking is the part
# worth testing, and it should not need a network or an API key to do it.

# TfNSW product classes. 99/100 are the two footpath flavours; the rest are
# vehicles, so "is this a change" and "is this walking" both fall out of it.
_WALK_CLASSES = {99, 100}
_MODE_NAMES = {1: "Train", 2: "Metro", 4: "Light Rail", 5: "Bus", 7: "Coach", 9: "Ferry", 11: "School bus"}

# Rail and metro. Used to pick which nearby stops are worth DRIVING to; the
# mode-biased searches that once used a bus counterpart are gone. Excluding a
# mode was the wrong axis: excluding buses to "force rail" also removed the
# feeder bus that makes a metro station reachable, so "343 to Waterloo, then
# the metro" was a journey that search could not return by construction.
_RAIL_CLASSES = {1, 2}

# How far to suggest walking to reach a better option. A tolerance, not a
# technical limit — 800 m is about ten minutes.
MAX_ACCESS_WALK_M = 800

# Park-and-ride is the expensive strategy: a stop lookup, a drive lookup and a
# trip query per candidate. Bounded hard, and pruned before any of that spends
# a request.
PARK_RIDE_MAX_CANDIDATES = 2
PARK_RIDE_MAX_DRIVE_MIN = 20
# Parking is not instant and TfNSW knows nothing about it. Charged explicitly
# at the call site so the arithmetic in add_access_leg stays honest rather than
# carrying a hidden allowance.
PARK_RIDE_PARKING_MIN = 5

TRIP_URL = "https://api.transport.nsw.gov.au/v1/tp/trip"
STOP_FINDER_URL = "https://api.transport.nsw.gov.au/v1/tp/stop_finder"
# The endpoint that answers "what is NEAR this point". stop_finder answers a
# different question — see is_real_stop_id.
COORD_URL = "https://api.transport.nsw.gov.au/v1/tp/coord"

# EFA location ids that are not stops. `coord:` is a reverse-geocoded ADDRESS
# echoed back at you, and it is the one that cost a week of wrong answers:
#
#   coord:4888949:3761579:GDAV:314 Gardeners Rd, Rosebery:0
#
# stop_finder with type_sf=coord returned exactly that and nothing else, so
# discovery saved ten routes hanging off a single fake stop at the user's own
# front door — every walk_min 0, every mode a bus, Green Square and the metro
# never considered because no real stop was ever in the list to filter.
#
# departure_mon accepts a coord: id and answers with a proximity scan, which is
# why the routes looked right and hid the problem. A real TfNSW stop id is a
# numeric global id; every pseudo-location carries a lowercase word prefix.
_PSEUDO_ID_PREFIXES = ("coord:", "poiid:", "streetid:", "loc:", "address:")


def is_real_stop_id(stop_id) -> bool:
    """True for a TfNSW stop id, False for an EFA pseudo-location.

    Deliberately a prefix denylist rather than "must be numeric": a future stop
    id with a letter in it should not be silently discarded, whereas every
    pseudo-location EFA emits is prefixed with what it is.
    """
    if not stop_id:
        return False
    text = str(stop_id).strip().lower()
    if not text:
        return False
    return not text.startswith(_PSEUDO_ID_PREFIXES)


def _parse_time(value):
    """ISO-8601 from TfNSW to an aware datetime, or None. Never raises."""
    if not value:
        return None
    try:
        from datetime import datetime as _dt
        parsed = _dt.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        from datetime import timezone as _tz
        parsed = parsed.replace(tzinfo=_tz.utc)
    return parsed


def parse_user_time(value):
    """A time the *user* asked for, to an aware datetime, or None. Never raises.

    Deliberately not `_parse_time`, which reads a naive timestamp as UTC. That
    is right for TfNSW, whose times always carry a zone, and wrong for anything
    a model writes: asked for "tomorrow at 7am" it emits `2026-09-05T07:00`
    with no offset, `_parse_time` calls that 07:00 UTC, and `_trip_params`
    converts it to 17:00 in Sydney. The trip is then planned, correctly and
    uselessly, for five in the afternoon.

    A bare wall-clock time means the wall clock the user is looking at.
    """
    parsed = _parse_time_naive_ok(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        from zoneinfo import ZoneInfo
        return parsed.replace(tzinfo=ZoneInfo(USER_TIMEZONE))
    return parsed


def _parse_time_naive_ok(value):
    """ISO-8601 to a datetime, zone preserved as written. None if unparseable."""
    if not value:
        return None
    try:
        from datetime import datetime as _dt
        return _dt.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def check_requested_time(arrive_by, depart_at, now):
    """The requested time as (arrive_dt, depart_dt), or a reason to refuse.

    Returns `(times, None)` when the request is usable and `(None, message)`
    when it is not. Pure, so the boundaries are testable without a network.

    Two ways a request is unusable, and they need different answers:

    - **Unparseable.** Say so rather than silently dropping it — a dropped
      `arrive_by` turns "get me there by 9" into "leave now", which looks like
      an answer and is not the one that was asked for.
    - **Already past.** Before the date landed in the system prompt the model
      dated from training and asked for 2024, and TfNSW answered a question
      about 2024 without complaint. Planning a journey into the past is never
      what was meant, so it is refused with the date it read, which is the
      detail that makes the mistake obvious.
    """
    for label, raw in (("arrive_by", arrive_by), ("depart_at", depart_at)):
        if raw and _parse_time_naive_ok(raw) is None:
            return None, (
                f"I couldn't read the time given for {label} ({raw!r}). "
                "Give it as ISO-8601, like 2026-09-05T07:00.")

    arrive = parse_user_time(arrive_by)
    depart = parse_user_time(depart_at)

    for label, when in (("arrive by", arrive), ("depart at", depart)):
        if when is not None and when < now:
            from zoneinfo import ZoneInfo
            local = when.astimezone(ZoneInfo(USER_TIMEZONE))
            return None, (
                f"That time has already passed — you asked to {label} "
                f"{local.strftime('%-I:%M %p on %A, %d %B %Y')}, which is in "
                "the past. Tell me the day and time you actually mean.")

    return (arrive, depart), None


def summarise_journey(journey: dict) -> dict | None:
    """Reduce one TfNSW journey to the numbers worth comparing.

    `wait_min` is the figure Google does not surface and the one that decides
    whether a route is actually pleasant: time standing on a platform between
    legs, as opposed to time moving. A journey that is two minutes quicker but
    puts eleven of them on a cold platform is not the better journey.

    `realtime` says whether ANY leg came back with an estimated time. A journey
    built purely from the timetable is a guess about the future; one carrying
    live data is not, and the difference is worth showing.
    """
    legs = journey.get("legs") or []
    if not legs:
        return None

    parsed_legs = []
    walk_min = 0
    vehicle_legs = 0
    realtime = False

    for leg in legs:
        origin = leg.get("origin") or {}
        dest = leg.get("destination") or {}
        product = (leg.get("transportation") or {}).get("product") or {}
        cls = product.get("class")

        dep_est = _parse_time(origin.get("departureTimeEstimated"))
        dep = dep_est or _parse_time(origin.get("departureTimePlanned"))
        arr_est = _parse_time(dest.get("arrivalTimeEstimated"))
        arr = arr_est or _parse_time(dest.get("arrivalTimePlanned"))
        if dep_est or arr_est:
            realtime = True

        minutes = int(round((leg.get("duration") or 0) / 60))
        is_walk = cls in _WALK_CLASSES or cls is None
        if is_walk:
            walk_min += minutes
        else:
            vehicle_legs += 1

        parsed_legs.append({
            "mode": "Walk" if is_walk else _MODE_NAMES.get(cls, "Service"),
            "line": (leg.get("transportation") or {}).get("disassembledName")
                    or (leg.get("transportation") or {}).get("number") or "",
            "from": origin.get("name") or "",
            "to": dest.get("name") or "",
            "depart": dep,
            "arrive": arr,
            "minutes": minutes,
            "realtime": bool(dep_est or arr_est),
        })

    departs = [l["depart"] for l in parsed_legs if l["depart"]]
    arrives = [l["arrive"] for l in parsed_legs if l["arrive"]]
    if not departs or not arrives:
        return None

    depart, arrive = min(departs), max(arrives)
    duration_min = int(round((arrive - depart).total_seconds() / 60))

    # Waiting is what is left once moving and walking are accounted for. Doing
    # it by subtraction rather than by summing the gaps means it stays right
    # even when a leg is missing a timestamp.
    moving_min = sum(l["minutes"] for l in parsed_legs)
    wait_min = max(0, duration_min - moving_min)

    return {
        "depart": depart,
        "arrive": arrive,
        "duration_min": duration_min,
        "walk_min": walk_min,
        "wait_min": wait_min,
        "changes": max(0, vehicle_legs - 1),
        "realtime": realtime,
        "legs": parsed_legs,
        "fare": _journey_fare(journey),
    }


def _journey_fare(journey: dict):
    """Cheapest adult Opal fare TfNSW quoted for this journey, or None.

    Per trip only. There is no API for your card's taps, so a running total
    against the daily or weekly cap would count the trips Sunday happened to
    plan and silently miss every other one — a number that looks authoritative
    and is not. Not worth having.
    """
    tickets = ((journey.get("fare") or {}).get("tickets")) or []
    prices = []
    for ticket in tickets:
        properties = ticket.get("properties") or {}
        price = ticket.get("priceBrutto")
        if price is None:
            continue
        if str(properties.get("evaluationTicket", "")).upper() in {"", "TICKET_TO_BE_SUPERSEDED"}:
            continue
        try:
            prices.append(float(price))
        except (TypeError, ValueError):
            continue
    return min(prices) if prices else None


def _dt_now_utc():
    """Now, as an aware UTC datetime. One place, so tests can reason about it."""
    from datetime import datetime as _dt, timezone as _tz
    return _dt.now(_tz.utc)


def haversine_m(a, b) -> float:
    """Metres between two (lat, lng) pairs. Straight line, not a route.

    Only ever used to decide whether a candidate is worth spending a request
    on, so a great-circle figure is precise enough — and free, which a routing
    call is not.
    """
    import math

    p1, p2 = math.radians(float(a[0])), math.radians(float(b[0]))
    dphi = math.radians(float(b[0]) - float(a[0]))
    dlam = math.radians(float(b[1]) - float(a[1]))
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * 6371000.0 * math.asin(min(1.0, math.sqrt(h)))


def station_is_toward(origin, station, destination, slack_m: float = 0.0) -> bool:
    """True if going to `station` first gets you closer to where you are going.

    Driving away from your destination to catch a train is occasionally right
    and usually wrong, and every candidate costs a drive lookup plus a trip
    query. This prunes the obviously-wrong ones for nothing, before any request
    is spent on them.
    """
    if not origin or not station or not destination:
        return False
    return haversine_m(station, destination) + slack_m < haversine_m(origin, destination)


def add_access_leg(summary: dict, access_min: int, mode: str = "Walk",
                   label: str = "your location") -> dict:
    """A copy of `summary` with the leg that gets you to its first stop added.

    This is the function that keeps a fanned-out search honest, and the reason
    the search is built the way it is. Ask TfNSW for a trip "from Green Square
    Station" and it answers with a journey that begins on the platform — the
    fourteen minutes it takes to reach that platform are simply absent from the
    response. Ranked against a baseline whose access walk IS counted, such an
    option wins on false pretences and sends you after a train you cannot
    physically reach.

    So the access leg goes back in explicitly: departure moves EARLIER, the
    duration grows by the same amount, and the leg is prepended so the answer
    can show it. `wait_min` is deliberately untouched — access is moving time,
    and it raises duration and moving time equally, which is exactly the case
    summarise_journey's subtraction already handles.

    Never mutates its input; callers still want the original to compare against.
    """
    from datetime import timedelta

    if not summary or not access_min or access_min <= 0:
        return summary

    depart = summary["depart"] - timedelta(minutes=access_min)
    legs = list(summary.get("legs") or [])
    access = {
        "mode": mode,
        "line": "",
        "from": label,
        "to": (legs[0].get("from") if legs else "") or "",
        "depart": depart,
        "arrive": summary["depart"],
        "minutes": access_min,
        "realtime": False,
    }

    out = dict(summary)
    out["depart"] = depart
    out["duration_min"] = summary["duration_min"] + access_min
    out["legs"] = [access] + legs
    if mode == "Walk":
        out["walk_min"] = summary.get("walk_min", 0) + access_min
    else:
        out["drive_min"] = summary.get("drive_min", 0) + access_min
    return out


def park_ride_depart_at(depart_at, access_min, now):
    """When to ask TfNSW to depart FROM the station, when planning forwards.

    The station query knows nothing about the drive to reach the station. Ask
    it for "leaving now" and it answers with a train that goes before you could
    possibly get there — which verify_journeys then correctly throws away, so
    park-and-ride would quietly never appear on an immediate query at all.
    Shifting the requested departure by the drive is what makes the option real
    rather than merely rejected.

    Only needed for forward planning. Given an arrival deadline TfNSW works
    backwards from it, and the drive is applied to the result by
    `add_access_leg` instead.
    """
    from datetime import timedelta as _td
    base = parse_user_time(depart_at) or now
    return (base + _td(minutes=max(0, access_min or 0))).isoformat()


def headway_from_departures(times) -> int | None:
    """Typical minutes between consecutive departures, or None.

    "Every 10 minutes" is the figure that decides what a wait means. Eleven
    minutes on a ten-minute service says you have just missed one and another
    is coming; the same eleven minutes on a half-hourly service says catch this
    or lose the morning. Nothing in the journey data carries it, so it is
    measured here from the departure board.

    The MEDIAN gap rather than the mean: one long gap across a timetable break
    drags an average to a number that matches no service actually running.
    Fewer than two departures returns None rather than a guess — an absent
    frequency is honest, a fabricated one looks like knowledge.
    """
    stamps = sorted(t for t in (times or []) if t)
    if len(stamps) < 2:
        return None
    gaps = [int(round((b - a).total_seconds() / 60)) for a, b in zip(stamps, stamps[1:])]
    gaps = sorted(g for g in gaps if g > 0)
    if not gaps:
        return None
    mid = len(gaps) // 2
    return gaps[mid] if len(gaps) % 2 else (gaps[mid - 1] + gaps[mid]) // 2


def choose_boarding_points(services, limit: int = 5) -> list:
    """One stop per distinct route, nearest first, capped at `limit`.

    Taking the nearest N stops is the obvious move and the wrong one. On a road
    served by a single bus, the five nearest stops are five stops on that bus,
    and five queries return the journey the baseline already found. Grouping by
    ROUTE first is what turns them into five genuinely different journeys — the
    343, the 358, the 306, the metro.

    Hidden rows are dropped. Where one route is reachable at several stops, the
    shortest walk wins. A row with no walk time sorts last rather than being
    discarded: not knowing how far it is, is not a reason to pretend it is not
    there.
    """
    best = {}
    for service in services or []:
        if not service or service.get("is_hidden"):
            continue
        route = (service.get("route") or "").strip()
        if not route:
            continue
        walk = service.get("walk_min")
        walk = 10 ** 6 if walk is None else walk
        current = best.get(route)
        if current is None or walk < current[0]:
            best[route] = (walk, service)

    ordered = sorted(best.values(),
                     key=lambda pair: (pair[0], pair[1].get("stop_name") or ""))
    return [service for _walk, service in ordered[:limit]]


def service_label(summary: dict) -> str:
    """"343 from Gardeners Rd" — the first thing you actually board.

    Walking and driving legs are skipped: they are how you reach the service,
    not the service. This is what lets an answer name the route rather than
    describing an anonymous journey.
    """
    for leg in (summary or {}).get("legs") or []:
        if leg.get("mode") in ("Walk", "Drive"):
            continue
        line = (leg.get("line") or "").strip()
        origin = (leg.get("from") or "").strip()
        if line and origin:
            return f"{line} from {origin}"
        return line or origin or ""
    return ""


def dedupe_journeys(summaries: list) -> list:
    """One entry per actual service. The strategies overlap, and should.

    The bus-biased and rail-biased searches routinely rediscover the option the
    baseline already found. Identity is the first vehicle leg — which service,
    leaving when — because that is the thing you physically catch. The first
    copy survives, which is the one from the earlier strategy in the list.
    """
    seen = set()
    out = []
    for s in summaries:
        if not s:
            continue
        vehicle = next((l for l in (s.get("legs") or []) if l.get("mode") != "Walk"), None)
        if vehicle and vehicle.get("depart"):
            key = (vehicle.get("line") or "", vehicle.get("from") or "",
                   vehicle["depart"].isoformat())
        else:
            key = ("walk", s["depart"].isoformat(), s["arrive"].isoformat())
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def verify_journeys(summaries: list, now, arrive_by=None, drive_only_min=None,
                    park_ride_min_saving: int = 0) -> list:
    """The "calculate and verify" step — drop what cannot or should not be taken.

    Nothing checked this before. Offering a journey that has already left is
    worse than offering none, because it looks like an answer.

    - A departure in the past is gone, however good it looked.
    - An arrival after `arrive_by` fails the one requirement that mattered.
    - A journey without usable times cannot be reasoned about at all.
    - Park-and-ride that loses to simply driving the whole way is not a plan.
    - Park-and-ride that barely beats the best transit is not worth the car.
      Driving is an occasional thing, so it has to clear a bar rather than
      appear whenever it is a minute quicker; `park_ride_min_saving` is that
      bar, measured against the best option that needs no car.
    """
    kept = []
    for s in summaries:
        if not s or not s.get("depart") or not s.get("arrive"):
            continue
        if s["depart"] < now:
            continue
        if arrive_by is not None and s["arrive"] > arrive_by:
            continue
        if (s.get("drive_min") and drive_only_min is not None
                and s["duration_min"] >= drive_only_min):
            continue
        kept.append(s)

    if not park_ride_min_saving:
        return kept

    # The bar is the best journey that asks nothing of the car. With none to
    # compare against, park-and-ride is the only option there is and stands.
    transit = [s["duration_min"] for s in kept if not s.get("drive_min")]
    if not transit:
        return kept
    bar = min(transit) - park_ride_min_saving
    return [s for s in kept
            if not s.get("drive_min") or s["duration_min"] <= bar]


def describe_strategy(summary: dict) -> str:
    """The short "why is this one here" label shown against an option.

    For a boarding-point option that is the service itself — naming the 343 is
    more use than saying "an alternative stop", because the route is how you
    think about it.
    """
    strategy = (summary or {}).get("strategy") or ""
    if strategy == "boarding":
        return service_label(summary)
    if strategy == "park_ride":
        station = next((l.get("from") for l in (summary.get("legs") or [])
                        if l.get("mode") not in ("Walk", "Drive") and l.get("from")), "")
        where = f" to {station}" if station else ""
        return f"drive {summary.get('drive_min') or 0} min{where}, then transit"
    return ""


def describe_frequency(summary: dict) -> str:
    """"every ~10 min", or "" when the frequency is not known.

    Deliberately silent rather than guessing. A wrong headway would be read as
    fact and change when someone leaves the house.
    """
    headway = (summary or {}).get("headway_min")
    if not headway or headway <= 0:
        return ""
    return f"every ~{headway} min"


def rank_journeys(summaries: list, arrive_by=None) -> list:
    """Best first. What "best" means depends on whether there is a deadline.

    **Leaving now**, the best journey is the one that arrives soonest. Waiting
    comes before changes because a single change with no wait beats a direct
    service you stand around for — the ordering Maps does not offer.

    **With a deadline**, arriving soonest is the wrong goal and produced a
    genuinely silly answer: asked to reach Kogarah by 9:00 AM, it picked the
    option leaving at 7:01 and arriving at 7:49, then reported a 48-minute
    journey and a two-hour-early departure in the same breath. Every option
    reaching this point already arrives in time — the gate rejects the ones
    that do not — so "earliest" was ranking on a question nobody asked and
    spending 71 minutes of the user's morning on a platform.

    What a deadline asks is *when do I need to leave*, so the winner is the
    **latest departure** that still makes it. Latest arrival would not do:
    a slow journey can arrive later while leaving earlier, which is the same
    bug wearing a different hat.

    Waiting, changes and duration break ties in both modes, in that order.
    """
    usable = [s for s in summaries if s]
    if arrive_by is not None:
        return sorted(usable, key=lambda s: (-s["depart"].timestamp(),
                                             s["wait_min"], s["changes"],
                                             s["duration_min"]))
    return sorted(
        usable,
        key=lambda s: (s["arrive"], s["wait_min"], s["changes"], s["duration_min"]),
    )


# However good an alternative's other properties, arriving this much later than
# the best option makes it a different plan rather than a variation on one.
_ALT_MAX_LATER_MIN = 15


def describe_alternative(best: dict, other: dict) -> str:
    """Why you might take `other` instead of `best`, or "" if you would not.

    An alternative has to be worth its delay. Left unfiltered this offered
    things like "5 min less walking — arrives 19 min later", which is a bad
    trade dressed up as a choice: the reason is true and the option is still
    wrong. So a saving denominated in minutes must at least cover the minutes
    it costs, and nothing arriving far later is pitched at all.

    Fewer changes is exempt from that arithmetic — it is a comfort argument,
    not a time one, and some people will take it for a few minutes.
    """
    later_arrival = int(round((other["arrive"] - best["arrive"]).total_seconds() / 60))
    if later_arrival > _ALT_MAX_LATER_MIN:
        return ""

    changes_saved = best["changes"] - other["changes"]
    wait_saved = max(0, best["wait_min"] - other["wait_min"])
    walk_saved = max(0, best["walk_min"] - other["walk_min"])

    # A later departure is a convenience, not a saving — it never pays for a
    # later arrival, so it is left out of this sum on purpose.
    if later_arrival > 0 and changes_saved <= 0 and (wait_saved + walk_saved) <= later_arrival:
        return ""

    reasons = []
    if changes_saved > 0:
        reasons.append(f"{changes_saved} fewer change{'s' if changes_saved != 1 else ''}")
    if wait_saved > 0:
        reasons.append(f"{wait_saved} min less waiting")
    if walk_saved > 0:
        reasons.append(f"{walk_saved} min less walking")

    later_departure = int(round((other["depart"] - best["depart"]).total_seconds() / 60))
    if later_departure > 0:
        reasons.append(f"leave {later_departure} min later")

    if not reasons:
        return ""
    cost = f"arrives {later_arrival} min later" if later_arrival > 0 else "same arrival"
    return f"{', '.join(reasons)} — {cost}"


def format_journeys(ranked: list, origin_note: str = "", limit: int = 3, drive=None) -> str:
    """The answer a person reads. Best option in full, alternatives by contrast."""
    if not ranked:
        return "No journeys found for that trip."

    from zoneinfo import ZoneInfo
    syd = ZoneInfo("Australia/Sydney")

    def clock(dt):
        return dt.astimezone(syd).strftime("%-I:%M %p")

    best = ranked[0]
    why = describe_strategy(best)
    out = [f"Best option{origin_note}: leave {clock(best['depart'])}, arrive {clock(best['arrive'])} "
           f"({best['duration_min']} min)" + (f" — {why}" if why else "")]

    detail = [f"{best['changes']} change{'s' if best['changes'] != 1 else ''}",
              f"{best['walk_min']} min walking",
              f"{best['wait_min']} min waiting"]
    frequency = describe_frequency(best)
    if frequency:
        detail.append(frequency)
    if best.get("fare") is not None:
        detail.append(f"${best['fare']:.2f} Opal")
    detail.append("live times" if best["realtime"] else "timetable only")
    out.append("  " + " · ".join(detail))

    for leg in best["legs"]:
        if leg["mode"] == "Walk":
            out.append(f"  · Walk {leg['minutes']} min to {leg['to']}")
        elif leg["mode"] == "Drive":
            out.append(f"  · Drive {leg['minutes']} min to {leg['to']} (parking included)")
        else:
            line = f" {leg['line']}" if leg["line"] else ""
            when = f" at {clock(leg['depart'])}" if leg["depart"] else ""
            live = "" if leg["realtime"] else " (scheduled)"
            out.append(f"  · {leg['mode']}{line} from {leg['from']}{when} → {leg['to']}{live}")

    # Said plainly rather than buried: TfNSW publishes no parking occupancy for
    # most car parks, so a park-and-ride that is best on paper can still fail
    # on arrival. Better to name the gap than to imply it was checked.
    if best.get("strategy") == "park_ride":
        out.append("  Parking availability is not checked — no feed covers it.")

    alternatives = []
    for other in ranked[1:]:
        reason = describe_alternative(best, other)
        if reason:
            label = describe_strategy(other)
            frequency = describe_frequency(other)
            note = " · ".join(x for x in (label, frequency) if x)
            alternatives.append(
                f"  · leave {clock(other['depart'])}, arrive {clock(other['arrive'])} "
                f"({other['duration_min']} min) — {reason}"
                + (f" [{note}]" if note else "")
            )
        if len(alternatives) >= limit - 1:
            break

    if alternatives:
        out.append("Alternatives:")
        out.extend(alternatives)

    # Always shown, even when transit wins comfortably: "would driving be
    # quicker?" is the question the answer is implicitly making a claim about,
    # and leaving it unstated makes the claim unverifiable.
    if drive and drive.get("minutes") is not None:
        delta = drive["minutes"] - best["duration_min"]
        if delta < 0:
            verdict = f"{abs(delta)} min faster than transit"
        elif delta > 0:
            verdict = f"{delta} min slower than transit"
        else:
            verdict = "about the same as transit"
        km = f", {drive['km']:.1f} km" if drive.get("km") is not None else ""
        out.append(f"Driving: {drive['minutes']} min{km} — {verdict}")

    return "\n".join(out)


def _coord_pair(raw):
    """TfNSW's [lat, lng], tolerant of the pair arriving the other way round.

    Sydney sits near (-33.9, 151.2), so a first element beyond ±90 can only be
    a longitude. The check costs nothing and removes a whole class of silently
    plausible wrong answers: a swapped pair does not raise, it just puts the
    station in the Indian Ocean, where every candidate quietly fails the
    "is it toward the destination" test and park-and-ride returns nothing at
    all — with no error to explain why.
    """
    if not raw or len(raw) < 2:
        return None
    try:
        a, b = float(raw[0]), float(raw[1])
    except (TypeError, ValueError):
        return None
    if abs(a) > 90 >= abs(b):
        a, b = b, a
    if not (-90 <= a <= 90 and -180 <= b <= 180):
        return None
    return (a, b)


def _route_minutes_km(data: dict):
    """(minutes, km) from an ORS GeoJSON response, or (None, None)."""
    features = (data or {}).get("features") or []
    if not features:
        return (None, None)
    summary = ((features[0].get("properties") or {}).get("summary")) or {}
    seconds, metres = summary.get("duration"), summary.get("distance")
    if seconds is None or metres is None:
        return (None, None)
    return (int(round(seconds / 60)), metres / 1000)


def as_efa_coord(latlng) -> str:
    """(lat, lng) as EFA's "lon:lat:EPSG:4326". Longitude FIRST.

    EFA is the one thing in this project that wants the pair the other way
    round, and getting it backwards does not fail — it silently plans a journey
    from the middle of the Indian Ocean and returns nothing, which is
    indistinguishable from "no services". Hence its own function and its own
    test.
    """
    return f"{float(latlng[1])}:{float(latlng[0])}:EPSG:4326"


def _trip_params(origin, destination, arrive_by=None, depart_at=None,
                 origin_type="any", destination_type="any") -> dict:
    """Query parameters for one TfNSW trip search."""
    params = {
        "outputFormat": "rapidJSON",
        "coordOutputFormat": "EPSG:4326",
        "depArrMacro": "arr" if arrive_by else "dep",
        "type_origin": origin_type,
        "name_origin": origin,
        "type_destination": destination_type,
        "name_destination": destination,
        "calcNumberOfTrips": 5,     # several, so there is something to rank
        "TfNSWTR": "true",          # real-time where it exists
        "version": "10.2.1.42",
        "itOptionsActive": 1,
        "computeMonomodalTripBicycle": "false",
    }
    # parse_user_time, not _parse_time: these two come from the model, and a
    # naive time it writes means the user's wall clock, not UTC.
    when = parse_user_time(arrive_by or depart_at)
    if when:
        from zoneinfo import ZoneInfo
        local = when.astimezone(ZoneInfo(USER_TIMEZONE))
        params["itdDate"] = local.strftime("%Y%m%d")
        params["itdTime"] = local.strftime("%H%M")
    return params


async def _fetch_journeys(http, headers, params) -> list:
    """Raw journeys for one strategy. Returns [] rather than raising.

    One strategy failing must not take the search down with it — that is the
    difference between a narrower answer and no answer. It also means that if
    TfNSW ignores or rejects the exclusion form, the biased searches simply
    contribute nothing and the baseline result stands, which is exactly
    today's behaviour rather than a regression.
    """
    try:
        res = await http.get(TRIP_URL, headers=headers, params=params, timeout=ORS_TIMEOUT)
        res.raise_for_status()
        data = res.json() or {}
    except Exception as e:
        print(f"[trip] a search failed, continuing without it: {e}", flush=True)
        return []

    journeys = data.get("journeys") or []
    if not journeys:
        # EFA explains itself here and we used to throw it away, which is how an
        # unresolvable address spent months looking like "no services run".
        notes = "; ".join(
            str(m.get("text") or m.get("error") or m)
            for m in (data.get("systemMessages") or [])
        )
        print(f"[trip] no journeys for {params.get('name_origin')} → "
              f"{params.get('name_destination')}"
              + (f" — TfNSW said: {notes}" if notes else " — TfNSW gave no reason"),
              flush=True)
    return journeys


async def _ors_route(http, start, end, profile="driving-car"):
    """(minutes, km) for one ORS route, or (None, None). Never raises."""
    try:
        res = await http.post(
            f"{ORS_BASE}/v2/directions/{profile}/geojson",
            headers={"Authorization": OPENROUTESERVICE_API_KEY,
                     "Content-Type": "application/json"},
            json={"coordinates": [start, end]},
            timeout=ORS_TIMEOUT,
        )
        res.raise_for_status()
        return _route_minutes_km(res.json())
    except Exception as e:
        print(f"[trip] ORS route failed: {e}", flush=True)
        return (None, None)


async def resolve_saved_label(client, user_id, text) -> dict | None:
    """`{origin, label}` when `text` names one of the user's saved places.

    Coordinates rather than the address string, for the same reason
    resolve_origin prefers them: they cannot be mis-geocoded on the way back
    out. Returns None for anything that is not a saved label, so a real place
    name falls through to the provider untouched.
    """
    if client is None or not user_id or not text:
        return None
    try:
        res = await asyncio.to_thread(
            lambda: client.table("saved_places")
            .select("label, address, lat, lng")
            .eq("user_id", user_id)
            .limit(20)
            .execute()
        )
    except Exception as e:
        print(f"[trip] could not read saved_places: {e}", flush=True)
        return None

    place = saved_place_match(text, getattr(res, "data", None) or [])
    if not place:
        return None
    if place.get("lat") is not None and place.get("lng") is not None:
        return {"origin": f"{place['lat']},{place['lng']}", "label": place["label"]}
    if place.get("address"):
        return {"origin": place["address"], "label": place["label"]}
    return None


async def resolve_place(http, headers, text, origin_ll=None,
                        allow_long_distance=False):
    """What `text` means, as a ResolvedPlace. Never raises.

    Replaces a geocoder that took the first candidate carrying a parseable
    coordinate, whatever it was — which is how "Sans Souci" became Narrabri and
    "Newtown" became the wrong Newtown. EFA returns isBest, matchQuality, type
    and a coordinate; all four are now used, and the choosing is done by
    `choose_place`, which is pure and tested.
    """
    params = {
        "outputFormat": "rapidJSON",
        "coordOutputFormat": "EPSG:4326",
        "type_sf": "any",
        "name_sf": text,
        "TfNSWSF": "true",
        "version": "10.2.1.42",
    }
    try:
        res = await http.get(STOP_FINDER_URL, headers=headers, params=params, timeout=20.0)
        res.raise_for_status()
        locations = (res.json() or {}).get("locations") or []
    except Exception as e:
        print(f"[trip] TfNSW geocode failed: {e}")
        return ResolvedPlace(
            requested=text, state=NOT_FOUND, source="provider",
            reason=("I couldn't reach the transit map just now, so I can't "
                    f"place '{text}'. Worth trying again in a moment."))

    candidates = [
        candidate_from_location(loc, _coord_pair, origin_ll, haversine_m)
        for loc in locations
    ]
    return choose_place(text, candidates,
                        allow_long_distance=allow_long_distance)


async def _tfnsw_geocode(http, headers, text):
    """An address to (lat, lng) via TfNSW stop_finder, or None. Never raises.

    The coordinates-only path, kept for callers that have no origin to measure
    against and no user to ask — park-and-ride station lookups and the driving
    comparison. Anything user-facing should go through `resolve_place`, which
    can say *why* it failed.
    """
    resolved = await resolve_place(http, headers, text)
    return resolved.coords()


async def _nearby_stations(http, headers, origin_ll, limit: int = 8,
                           radius_m: float = PARK_RIDE_RADIUS_M) -> list:
    """Rail stations within `radius_m` of a coordinate. [] rather than raising.

    stop_finder returns what is nearest without a distance bound of its own, so
    the radius is applied here. 5 km by default — far enough to reach a station
    worth driving to, close enough that the drive stays "once in a while".
    """
    # /v1/tp/coord, for the same reason discovery moved to it: stop_finder with
    # type_sf=coord reverse-geocodes and returns the ADDRESS as a single
    # `coord:` pseudo-location. Its productClasses said "bus", the rail filter
    # below then rejected it, and park-and-ride has therefore never produced a
    # single candidate — silently, because an empty list is also what "no
    # station nearby" looks like.
    efa_coord = f"{origin_ll[1]}:{origin_ll[0]}:EPSG:4326"
    locations = []
    for type_1 in ("STOP", "GIS_POINT"):
        try:
            res = await http.get(
                COORD_URL, headers=headers, timeout=ORS_TIMEOUT,
                params={"outputFormat": "rapidJSON",
                        "coordOutputFormat": "EPSG:4326",
                        "coord": efa_coord, "inclFilter": 1, "type_1": type_1,
                        "radius_1": int(radius_m), "version": "10.2.1.42"})
            res.raise_for_status()
            found = (res.json() or {}).get("locations") or []
        except Exception as e:
            print(f"[trip] coord({type_1}) failed: {e}", flush=True)
            continue
        if any(is_real_stop_id(loc.get("id")) for loc in found):
            locations = found
            break

    if not locations:
        print("[trip] no stations found near the origin — park-and-ride "
              "has nothing to offer for this trip", flush=True)
        return []

    out = []
    for loc in locations:
        if not is_real_stop_id(loc.get("id")):
            continue
        classes = set(loc.get("productClasses") or [])
        # No productClasses at all is kept: absent data is not evidence against.
        if classes and not (classes & _RAIL_CLASSES):
            continue
        coord = _coord_pair(loc.get("coord"))
        if not coord:
            continue
        if haversine_m(origin_ll, coord) > radius_m:
            continue
        out.append({"id": loc.get("id"), "name": loc.get("name") or "",
                    "lat": coord[0], "lng": coord[1]})
        if len(out) >= limit:
            break
    return out


async def _drive_and_park_ride(http, headers, origin, destination,
                               arrive_by=None, depart_at=None,
                               origin_ll=None, dest_ll=None):
    """The driving comparison, and any park-and-ride worth considering.

    Both need the same two geocodes, so they share them. Returns
    `({minutes, km} | None, [summaries])` and never raises: losing the driving
    line must not lose the transit answer.

    Park-and-ride is the one strategy that cannot keep the real origin — the
    transit query has to start at the station — so its drive leg is added back
    explicitly by `add_access_leg`, plus a parking allowance. Without that the
    option would be ranked as though you teleported to the car park.
    """
    # plan_journeys has already resolved both ends through TfNSW, so reuse them
    # rather than paying ORS for the same answer — and so this works at all when
    # there is no ORS geocoding quota left.
    start = [origin_ll[1], origin_ll[0]] if origin_ll else None
    end = [dest_ll[1], dest_ll[0]] if dest_ll else None
    if not start or not end:
        try:
            start = start or _as_lonlat(origin) or await _ors_geocode(http, origin)
            end = end or _as_lonlat(destination) or await _ors_geocode(http, destination)
        except Exception as e:
            print(f"[trip] geocode failed: {e}", flush=True)
            return (None, [])
    if not start or not end:
        return (None, [])

    minutes, km = await _ors_route(http, start, end, "driving-car")
    drive = {"minutes": minutes, "km": km} if minutes is not None else None

    origin_ll = (start[1], start[0])     # ORS speaks [lon, lat]; compare in (lat, lng)
    dest_ll = (end[1], end[0])

    stations = await _nearby_stations(http, headers, origin_ll)
    candidates = [st for st in stations
                  if station_is_toward(origin_ll, (st["lat"], st["lng"]), dest_ll)]

    summaries = []
    for station in candidates[:PARK_RIDE_MAX_CANDIDATES]:
        drive_min, _km = await _ors_route(
            http, start, [station["lng"], station["lat"]], "driving-car")
        if drive_min is None or drive_min > PARK_RIDE_MAX_DRIVE_MIN:
            continue
        access_min = drive_min + PARK_RIDE_PARKING_MIN
        # With a deadline TfNSW plans backwards and needs no shift; without one
        # it must be told you cannot board until you have driven there.
        station_depart = depart_at if arrive_by else park_ride_depart_at(
            depart_at, access_min, _dt_now_utc())
        raw = await _fetch_journeys(http, headers, _trip_params(
            station.get("id") or station["name"], destination,
            arrive_by, station_depart,
            origin_type="stop" if station.get("id") else "any"))
        for journey in raw:
            summary = summarise_journey(journey)
            if not summary:
                continue
            summary["strategy"] = "park_ride"
            summaries.append(add_access_leg(summary, access_min, mode="Drive"))
    return (drive, summaries)


async def load_nearby_services(client, user_id: str, place_label: str = "home") -> list:
    """The learned local network for a place: usable services, nearest first.

    Read-only and forgiving — a missing table or an empty inventory means the
    search falls back to the baseline alone, which is what shipped before this
    existed. Travel should degrade, not fail, when the weekly refresh has not
    run yet.
    """
    if client is None or not user_id:
        return []
    try:
        res = await asyncio.to_thread(
            lambda: client.table("nearby_services")
            .select("stop_id, stop_name, route, headsign, mode_class, headway_min, walk_min, is_hidden")
            .eq("user_id", user_id)
            .eq("place_label", place_label)
            .eq("is_hidden", False)
            .order("walk_min")
            .limit(100)
            .execute()
        )
    except Exception as e:
        print(f"[trip] could not read nearby_services: {e}", flush=True)
        return []

    rows = getattr(res, "data", None) or []

    # Rows saved before discovery learned the difference between a stop and an
    # address. They carry a `coord:` pseudo-id at the user's own front door, so
    # every one reports walk_min 0 and sorts above every real stop — which
    # would let a fixed discovery still lose to the data the broken one left
    # behind. Dropped on read rather than deleted: a read filter cannot destroy
    # a row the user corrected by hand, and it keeps working if any survive.
    usable = [r for r in rows if is_real_stop_id(r.get("stop_id"))]
    if len(usable) != len(rows):
        print(f"[trip] ignoring {len(rows) - len(usable)} nearby_services row(s) "
              "attached to an address rather than a stop", flush=True)
    return usable


async def plan_journeys(
    destination: str,
    origin: str | None = None,
    arrive_by: str | None = None,
    depart_at: str | None = None,
    client=None,
    user_id: str | None = None,
    depth: str = "full",
) -> dict:
    """Ranked journeys as data: `{ok, journeys, origin_note, drive}` or `{ok, error}`.

    Runs a search rather than a query. Asked once, TfNSW answers with five
    departures along the single corridor it picked — so a place served by four
    routes is only ever offered one of them, and ranking cannot recover the
    three it never saw.

    So the boarding points are enumerated instead, from the learned local
    network (`nearby_services`):

        baseline    from the real origin, whatever TfNSW thinks best
        boarding    one query per distinct nearby ROUTE, walk charged back
        park+ride   drive to a station toward the destination, then transit

    Grouping by route rather than by proximity is the point: five nearest stops
    on one road are five stops on the same bus. `choose_boarding_points` picks
    the 343, the 358, the 306 and the metro instead.

    Everything that does not start at the real origin pays for its access leg
    through `add_access_leg`, so a journey that begins on a platform cannot win
    by hiding the walk that gets you there.

    `depth="baseline"` runs only the first search. travel_watch uses it so a
    job ticking every five minutes does not spend a fan-out per event.
    """
    if not TFNSW_API_KEY:
        return {"ok": False, "error": "Error: TFNSW_API_KEY is not set."}

    # Before anything is looked up or fetched. The system prompt now states the
    # date, which stops the model dating from training — but a prompt is a
    # request, not a guarantee, and this is the one check that does not depend
    # on the model having read it.
    times, time_error = check_requested_time(arrive_by, depart_at, _dt_now_utc())
    if time_error:
        return {"ok": False, "error": time_error}
    arrive_dt, _ = times

    origin_note = ""
    if not origin:
        if client is None or not user_id:
            return {"ok": False, "error": "Error: no origin given and no user context to look one up."}
        resolved = await resolve_origin(client, user_id)
        if not resolved:
            return {"ok": False, "error": (
                "I don't know where you're starting from — no recent location "
                "and no default saved place. Add one under Settings → Places.")}
        origin = resolved["origin"]
        origin_note = f" (from {resolved['source']})"
    else:
        # `origin="home"` is the model naming a saved place rather than omitting
        # the argument, and it used to be sent to EFA as free text. It matched
        # some other Home in NSW and produced a journey leaving at 6:20 PM to
        # arrive at 3:07 PM — 1248 minutes, 783 of them waiting — which was then
        # offered as the best option. Omitting the origin had always worked
        # because that path reads saved_places; naming it did not, because this
        # one did not. Same lookup, both ways in.
        saved = await resolve_saved_label(client, user_id, origin)
        if saved:
            origin = saved["origin"]
            origin_note = f" (from {saved['label']})"

    headers = {"Authorization": f"apikey {TFNSW_API_KEY}", "Accept": "application/json"}
    full = depth != "baseline"

    boarding = []
    if full:
        boarding = choose_boarding_points(
            await load_nearby_services(client, user_id), BOARDING_POINT_LIMIT)

    # `http`, not `client`: `client` is the Supabase handle this function takes.
    async with httpx.AsyncClient() as http:
        # Resolve both ends to coordinates FIRST. /trip with type=any and a
        # free-text postal address does not error when it cannot place the
        # address — it returns an empty journeys array, which is
        # indistinguishable from "no services run". That is why every trip this
        # project has ever planned came back empty. stop_finder resolves the
        # same text happily, so it goes through there first.
        origin_ll = _as_lonlat(origin)
        if origin_ll:
            origin_ll = (origin_ll[1], origin_ll[0])
        else:
            resolved_origin = await resolve_place(http, headers, origin)
            if not resolved_origin.ok:
                return {"ok": False, "error": resolved_origin.reason}
            origin_ll = resolved_origin.coords()

        # The destination is measured against the origin, which is what turns
        # "Sans Souci" resolving to Narrabri from an answer into a rejection.
        # Distance is only meaningful once the start is known, so this runs
        # second rather than alongside.
        dest_ll = _as_lonlat(destination)
        if dest_ll:
            dest_ll = (dest_ll[1], dest_ll[0])
        else:
            resolved_dest = await resolve_place(http, headers, destination,
                                                origin_ll=origin_ll)
            if not resolved_dest.ok:
                # Ambiguous, implausible and not-found each keep their own
                # wording. Collapsing them is what produced "there's a
                # limitation with the public transport data" when the truth was
                # "I looked up the wrong Newtown".
                return {"ok": False, "error": resolved_dest.reason}
            dest_ll = resolved_dest.coords()

        # Coordinates from here on: unambiguous, and they cannot be
        # re-interpreted differently by each query in the fan-out.
        origin_ref, origin_kind = as_efa_coord(origin_ll), "coord"
        dest_ref, dest_kind = as_efa_coord(dest_ll), "coord"

        baseline_params = _trip_params(origin_ref, dest_ref, arrive_by, depart_at,
                                       origin_type=origin_kind,
                                       destination_type=dest_kind)
        boarding_params = [
            _trip_params(service.get("stop_id") or service.get("stop_name"),
                         dest_ref, arrive_by, depart_at,
                         origin_type="stop" if service.get("stop_id") else "any",
                         destination_type=dest_kind)
            for service in boarding
        ]

        results = await asyncio.gather(
            *[_fetch_journeys(http, headers, p)
              for p in [baseline_params] + boarding_params]
        )

        summaries = []
        for journey in results[0]:
            summary = summarise_journey(journey)
            if summary:
                summary["strategy"] = "baseline"
                summaries.append(summary)

        for service, raw in zip(boarding, results[1:]):
            walk_min = service.get("walk_min") or 0
            for journey in raw:
                summary = summarise_journey(journey)
                if not summary:
                    continue
                summary["strategy"] = "boarding"
                # Frequency rides along from the weekly refresh: no extra
                # request, and it is the figure that says what a wait means.
                summary["headway_min"] = service.get("headway_min")
                summaries.append(add_access_leg(
                    summary, walk_min, mode="Walk",
                    label="your location") if walk_min else summary)

        drive = None
        if full and OPENROUTESERVICE_API_KEY:
            drive, park_ride = await _drive_and_park_ride(
                http, headers, origin, destination, arrive_by, depart_at,
                origin_ll=origin_ll, dest_ll=dest_ll)
            summaries.extend(park_ride)

    if not summaries:
        # Both ends resolved — otherwise we returned above — so this really is
        # "found the places, no services", not "couldn't find the places". The
        # distinction matters: the old message claimed the latter was the
        # former, and Sunday repeated that to the user as fact.
        when = "around then" if (arrive_by or depart_at) else "right now"
        return {"ok": False, "error": (
            f"I found both places, but TfNSW has no public transport journeys "
            f"from there to {destination} {when}. Worth trying a different time.")}

    deduped = dedupe_journeys(summaries)
    checked = verify_journeys(deduped, _dt_now_utc(), arrive_dt,
                              (drive or {}).get("minutes"),
                              PARK_RIDE_MIN_SAVING_MIN)

    # The plausibility gate, after the existing checks and before ranking.
    # verify_journeys asks whether an option is worse than another option;
    # this asks whether it is an option at all. Both of the itineraries that
    # reached chat as "Best option" — 1248 minutes arriving before it departed,
    # and 1953 minutes via Werris Creek — passed everything that existed and
    # fail several rules here independently.
    checked, rejected = gate_journeys(
        checked, _dt_now_utc(), arrive_dt, (drive or {}).get("minutes"))

    if not checked:
        # Say what was wrong with what was found. "None of them work" invites a
        # retry of the same question; naming the fault is what lets the user —
        # or the model — change something that matters.
        detail = rejection_summary(rejected)
        return {"ok": False, "error": (
            f"I found {len(rejected)} journey(s) to {destination} and none of "
            f"them are usable: {detail}." if detail else
            f"I found journeys to {destination}, but none of them work: they have "
            "either already departed or arrive too late.")}

    # arrive_dt, so a deadline ranks by the latest departure that makes it
    # rather than by the earliest arrival. Without it, "get me there by 9"
    # answers "leave at 7 and wait an hour", which is true and useless.
    ranked = rank_journeys(checked, arrive_dt)
    if not ranked:
        return {"ok": False,
                "error": f"TfNSW returned journeys for {destination} but none had usable times."}

    return {"ok": True, "journeys": ranked, "origin_note": origin_note, "drive": drive}


async def trip_plan(
    destination: str,
    origin: str | None = None,
    arrive_by: str | None = None,
    depart_at: str | None = None,
    client=None,
    user_id: str | None = None,
) -> str:
    """Search for a way there, rank the options, and say why each is offered.

    Uses TfNSW rather than Google because the legs carry live departure
    estimates rather than a timetable — and, more to the point, because this
    runs several biased searches at once (see plan_journeys) instead of taking
    the first corridor a planner suggests. That is what surfaces the bus from
    the next street, or the station worth driving to.

    `arrive_by` / `depart_at` are ISO-8601. Give `arrive_by` when there is a
    meeting to be at; that is what makes a leave-by time meaningful.
    """
    result = await plan_journeys(destination, origin, arrive_by, depart_at, client, user_id)
    if not result["ok"]:
        return result["error"]
    return format_journeys(result["journeys"], result["origin_note"],
                           drive=result.get("drive"))


def format_services(services: list, place: str = "home") -> str:
    """The local network as a person reads it, grouped by stop.

    Answers "what runs near me" without planning anything — the question you
    ask when deciding whether Sunday actually knows your area, and the place a
    wrong or missing route becomes visible.
    """
    usable = [s for s in (services or []) if s and not s.get("is_hidden")]
    if not usable:
        return (f"I don't know what runs near {place} yet. The weekly "
                "refresh_nearby_services job discovers it; it may not have run.")

    by_stop = {}
    for service in sorted(usable, key=lambda s: (s.get("walk_min") is None,
                                                 s.get("walk_min") or 0,
                                                 s.get("stop_name") or "")):
        by_stop.setdefault(service.get("stop_name") or "Unknown stop", []).append(service)

    out = [f"Services near {place}:"]
    for stop_name, at_stop in by_stop.items():
        walk = at_stop[0].get("walk_min")
        walk_note = f" ({walk} min walk)" if walk is not None else ""
        out.append(f"{stop_name}{walk_note}")
        for service in at_stop:
            headsign = service.get("headsign")
            where = f" to {headsign}" if headsign else ""
            frequency = describe_frequency(service)
            how_often = f" · {frequency}" if frequency else ""
            edited = " · yours" if service.get("source") == "user" else ""
            out.append(f"  · {service.get('route') or '?'}{where}{how_often}{edited}")
    return "\n".join(out)


async def nearby_services(client=None, user_id: str | None = None,
                          place: str = "home") -> str:
    """What public transport runs near a saved place, and how often."""
    if client is None or not user_id:
        return "Error: no user context to look up saved places for."
    services = await load_nearby_services(client, user_id, place)
    return format_services(services, place)


def leave_time_from(journeys: list, buffer_minutes: int):
    """When to walk out of the door for the best journey, or None.

    The first leg's departure less a buffer. Pure, because this is the number
    an alert fires on and getting it wrong by five minutes is the whole ball
    game — it should be testable without a network.
    """
    if not journeys:
        return None
    from datetime import timedelta as _td
    return journeys[0]["depart"] - _td(minutes=max(0, buffer_minutes))


async def leave_by(
    destination: str,
    arrive_by: str,
    origin: str | None = None,
    client=None,
    user_id: str | None = None,
) -> str:
    """When to leave to arrive somewhere on time, with the journey behind it."""
    result = await plan_journeys(destination, arrive_by=arrive_by,
                                 origin=origin, client=client, user_id=user_id)
    if not result["ok"]:
        return result["error"]

    journeys = result["journeys"]
    depart = leave_time_from(journeys, TRAVEL_BUFFER_MINUTES)
    if depart is None:
        return f"No journeys found to {destination}."

    from zoneinfo import ZoneInfo
    syd = ZoneInfo("Australia/Sydney")
    best = journeys[0]
    # Naming the strategy matters most here: when the best option is
    # park-and-ride, the leave time already has the drive and parking in it,
    # and a bare clock time would look inexplicably early.
    label = describe_strategy(best)
    return (
        f"Leave by {depart.astimezone(syd).strftime('%-I:%M %p')}"
        f"{result['origin_note']} to arrive {best['arrive'].astimezone(syd).strftime('%-I:%M %p')}"
        f" — {best['duration_min']} min, {best['changes']} change"
        f"{'s' if best['changes'] != 1 else ''}, {best['walk_min']} min walking."
        + (f" Via {label}." if label else "")
        + f" (Includes a {TRAVEL_BUFFER_MINUTES} min buffer.)"
    )


# ── Startup health checks ───────────────────────────────────────────────────
# "The key is present" is not the same claim as "the key works", and the gap
# between them is how trip_plan shipped three times without ever running. One
# real call each, at startup, so the banner states a fact.

async def check_tfnsw() -> tuple[bool, str]:
    """One stop_finder call. Proves the key, the host and the response shape."""
    if not TFNSW_API_KEY:
        return False, "TFNSW_API_KEY unset — transit planning unavailable"
    try:
        async with httpx.AsyncClient() as http:
            res = await http.get(
                "https://api.transport.nsw.gov.au/v1/tp/stop_finder",
                headers={"Authorization": f"apikey {TFNSW_API_KEY}", "Accept": "application/json"},
                params={"outputFormat": "rapidJSON", "type_sf": "any",
                        "name_sf": "Central Station", "coordOutputFormat": "EPSG:4326",
                        "TfNSWSF": "true", "version": "10.2.1.42"},
                timeout=10.0,
            )
        if res.status_code in (401, 403):
            return False, f"TfNSW rejected the key (HTTP {res.status_code})"
        res.raise_for_status()
        locations = (res.json() or {}).get("locations") or []
        if not locations:
            return False, "TfNSW answered but found no stops — unexpected response shape"
        return True, f"stop_finder returned {locations[0].get('name', 'a stop')}"
    except Exception as e:
        return False, f"not reachable: {e}"


async def check_openrouteservice() -> tuple[bool, str]:
    """One geocode call, out of 2000/day."""
    if not OPENROUTESERVICE_API_KEY:
        return False, ("OPENROUTESERVICE_API_KEY unset — driving directions "
                       "unavailable; transit unaffected")
    try:
        async with httpx.AsyncClient() as http:
            coords = await _ors_geocode(http, "Central Station, Sydney NSW")
        if not coords:
            return False, "ORS answered but geocoded nothing — unexpected response shape"
        return True, f"geocoder returned {coords[1]:.3f},{coords[0]:.3f}"
    except Exception as e:
        return False, f"not reachable: {e}"
