import asyncio
import httpx
import json
import re
from config import OPENROUTESERVICE_API_KEY, TFNSW_API_KEY, TRAVEL_BUFFER_MINUTES
from utils import resolve_origin

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

# Mode families for the biased searches. One query excluding rail forces
# options that board at a nearby bus stand; one excluding bus forces the walk
# or feeder ride to a station. Both keep the REAL origin, so TfNSW still costs
# the access walk itself and the results stay directly comparable.
_RAIL_CLASSES = {1, 2}
_BUS_CLASSES = {5, 7, 11}

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
    base = _parse_time(depart_at) or now
    return (base + _td(minutes=max(0, access_min or 0))).isoformat()


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


def verify_journeys(summaries: list, now, arrive_by=None, drive_only_min=None) -> list:
    """The "calculate and verify" step — drop what cannot actually be taken.

    Nothing checked this before. Offering a journey that has already left is
    worse than offering none, because it looks like an answer. Four rules:

    - A departure in the past is gone, however good it looked.
    - An arrival after `arrive_by` fails the one requirement that mattered.
    - Park-and-ride that loses to simply driving the whole way is not a plan.
    - A journey without usable times cannot be reasoned about at all.
    """
    out = []
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
        out.append(s)
    return out


def describe_strategy(summary: dict) -> str:
    """The short "why is this one here" label shown against an option."""
    strategy = (summary or {}).get("strategy") or ""
    if strategy == "bus":
        return "bus only — no station walk"
    if strategy == "rail":
        return "via a station"
    if strategy == "park_ride":
        station = next((l.get("from") for l in (summary.get("legs") or [])
                        if l.get("mode") not in ("Walk", "Drive") and l.get("from")), "")
        where = f" to {station}" if station else ""
        return f"drive {summary.get('drive_min') or 0} min{where}, then transit"
    return ""


def rank_journeys(summaries: list) -> list:
    """Best first: earliest arrival, then least waiting, then fewest changes.

    Arrival wins because that is what a calendar cares about. Waiting comes
    before changes because a single change with no wait beats a direct service
    you stand around for — which is the ordering Maps does not offer.
    """
    return sorted(
        [s for s in summaries if s],
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
            alternatives.append(
                f"  · leave {clock(other['depart'])}, arrive {clock(other['arrive'])} "
                f"({other['duration_min']} min) — {reason}"
                + (f" [{label}]" if label else "")
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


def _exclude_params(classes) -> dict:
    """EFA's exclusion form: a checkbox flag plus one key per excluded class.

    This is what biases a search WITHOUT moving the origin, and keeping the
    real starting address on every query is the whole trick — TfNSW costs the
    access walk itself, so no leg has to be added back by hand and the results
    from different searches stay directly comparable.
    """
    if not classes:
        return {}
    params = {"excludedMeans": "checkbox"}
    for cls in sorted(classes):
        params[f"exclMOT_{cls}"] = 1
    return params


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


def _trip_params(origin, destination, arrive_by=None, depart_at=None,
                 exclude=None, origin_type="any") -> dict:
    """Query parameters for one TfNSW trip search."""
    params = {
        "outputFormat": "rapidJSON",
        "coordOutputFormat": "EPSG:4326",
        "depArrMacro": "arr" if arrive_by else "dep",
        "type_origin": origin_type,
        "name_origin": origin,
        "type_destination": "any",
        "name_destination": destination,
        "calcNumberOfTrips": 5,     # several, so there is something to rank
        "TfNSWTR": "true",          # real-time where it exists
        "version": "10.2.1.42",
        "itOptionsActive": 1,
        "computeMonomodalTripBicycle": "false",
    }
    when = _parse_time(arrive_by or depart_at)
    if when:
        from zoneinfo import ZoneInfo
        local = when.astimezone(ZoneInfo("Australia/Sydney"))
        params["itdDate"] = local.strftime("%Y%m%d")
        params["itdTime"] = local.strftime("%H%M")
    params.update(_exclude_params(exclude))
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
        return (res.json() or {}).get("journeys") or []
    except Exception as e:
        print(f"[trip] a search failed, continuing without it: {e}", flush=True)
        return []


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


async def _nearby_stations(http, headers, origin_ll, limit: int = 8) -> list:
    """Rail stations near a coordinate, nearest first. [] rather than raising."""
    params = {
        "outputFormat": "rapidJSON",
        "coordOutputFormat": "EPSG:4326",
        "type_sf": "coord",
        # EFA wants X:Y, which is lon:lat — the opposite of everything else here.
        "name_sf": f"{origin_ll[1]}:{origin_ll[0]}:EPSG:4326",
        "TfNSWSF": "true",
        "version": "10.2.1.42",
    }
    try:
        res = await http.get(STOP_FINDER_URL, headers=headers, params=params,
                             timeout=ORS_TIMEOUT)
        res.raise_for_status()
        locations = (res.json() or {}).get("locations") or []
    except Exception as e:
        print(f"[trip] stop_finder failed: {e}", flush=True)
        return []

    out = []
    for loc in locations:
        classes = set(loc.get("productClasses") or [])
        # No productClasses at all is kept: absent data is not evidence against.
        if classes and not (classes & _RAIL_CLASSES):
            continue
        coord = _coord_pair(loc.get("coord"))
        if not coord:
            continue
        out.append({"id": loc.get("id"), "name": loc.get("name") or "",
                    "lat": coord[0], "lng": coord[1]})
        if len(out) >= limit:
            break
    return out


async def _drive_and_park_ride(http, headers, origin, destination,
                               arrive_by=None, depart_at=None):
    """The driving comparison, and any park-and-ride worth considering.

    Both need the same two geocodes, so they share them. Returns
    `({minutes, km} | None, [summaries])` and never raises: losing the driving
    line must not lose the transit answer.

    Park-and-ride is the one strategy that cannot keep the real origin — the
    transit query has to start at the station — so its drive leg is added back
    explicitly by `add_access_leg`, plus a parking allowance. Without that the
    option would be ranked as though you teleported to the car park.
    """
    try:
        start = _as_lonlat(origin) or await _ors_geocode(http, origin)
        end = _as_lonlat(destination) or await _ors_geocode(http, destination)
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
    departures along the single corridor it picked — which is why one query can
    never beat Maps: it never considers a second route. So several searches run
    concurrently from the SAME origin, biased by mode, plus park-and-ride when
    that is plausible:

        baseline    whatever TfNSW thinks best
        bus         rail excluded, forcing nearby bus stands
        rail        bus excluded, forcing the walk or feeder ride to a station
        park+ride   drive to a station that is toward the destination, then transit

    Everything except park-and-ride keeps the real origin, so TfNSW costs each
    access walk itself and the pool is directly comparable. Park-and-ride pays
    for its own drive leg through `add_access_leg`.

    `depth="baseline"` runs only the first search. travel_watch uses it so a
    job ticking every five minutes does not spend four searches per event.

    Split out of trip_plan so leave_by and travel_watch can do arithmetic on
    the result rather than parsing a formatted string back into times.
    """
    if not TFNSW_API_KEY:
        return {"ok": False, "error": "Error: TFNSW_API_KEY is not set."}

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

    headers = {"Authorization": f"apikey {TFNSW_API_KEY}", "Accept": "application/json"}
    full = depth != "baseline"

    searches = [("baseline", None)]
    if full:
        searches += [("bus", _RAIL_CLASSES), ("rail", _BUS_CLASSES)]

    # `http`, not `client`: `client` is the Supabase handle this function takes.
    async with httpx.AsyncClient() as http:
        results = await asyncio.gather(*[
            _fetch_journeys(http, headers,
                            _trip_params(origin, destination, arrive_by, depart_at, exclude))
            for _label, exclude in searches
        ])

        summaries = []
        for (label, _exclude), raw in zip(searches, results):
            for journey in raw:
                summary = summarise_journey(journey)
                if summary:
                    summary["strategy"] = label
                    summaries.append(summary)

        drive = None
        if full and OPENROUTESERVICE_API_KEY:
            drive, park_ride = await _drive_and_park_ride(
                http, headers, origin, destination, arrive_by, depart_at)
            summaries.extend(park_ride)

    if not summaries:
        return {"ok": False,
                "error": f"No public transport journeys found from {origin} to {destination}."}

    deduped = dedupe_journeys(summaries)
    checked = verify_journeys(deduped, _dt_now_utc(), _parse_time(arrive_by),
                              (drive or {}).get("minutes"))
    if not checked:
        return {"ok": False, "error": (
            f"I found journeys to {destination}, but none of them work: they have "
            "either already departed or arrive too late.")}

    ranked = rank_journeys(checked)
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
