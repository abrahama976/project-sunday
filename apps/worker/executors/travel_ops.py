import httpx
import json
import re
from config import OPENROUTESERVICE_API_KEY, TFNSW_API_KEY
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

TRIP_URL = "https://api.transport.nsw.gov.au/v1/tp/trip"


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


def format_journeys(ranked: list, origin_note: str = "", limit: int = 3) -> str:
    """The answer a person reads. Best option in full, alternatives by contrast."""
    if not ranked:
        return "No journeys found for that trip."

    from zoneinfo import ZoneInfo
    syd = ZoneInfo("Australia/Sydney")

    def clock(dt):
        return dt.astimezone(syd).strftime("%-I:%M %p")

    best = ranked[0]
    out = [f"Best option{origin_note}: leave {clock(best['depart'])}, arrive {clock(best['arrive'])} "
           f"({best['duration_min']} min)"]

    detail = [f"{best['changes']} change{'s' if best['changes'] != 1 else ''}",
              f"{best['walk_min']} min walking",
              f"{best['wait_min']} min waiting"]
    if best["fare"] is not None:
        detail.append(f"${best['fare']:.2f} Opal")
    detail.append("live times" if best["realtime"] else "timetable only")
    out.append("  " + " · ".join(detail))

    for leg in best["legs"]:
        if leg["mode"] == "Walk":
            out.append(f"  · Walk {leg['minutes']} min to {leg['to']}")
        else:
            line = f" {leg['line']}" if leg["line"] else ""
            when = f" at {clock(leg['depart'])}" if leg["depart"] else ""
            live = "" if leg["realtime"] else " (scheduled)"
            out.append(f"  · {leg['mode']}{line} from {leg['from']}{when} → {leg['to']}{live}")

    alternatives = []
    for other in ranked[1:]:
        why = describe_alternative(best, other)
        if why:
            alternatives.append(
                f"  · leave {clock(other['depart'])}, arrive {clock(other['arrive'])} "
                f"({other['duration_min']} min) — {why}"
            )
        if len(alternatives) >= limit - 1:
            break

    if alternatives:
        out.append("Alternatives:")
        out.extend(alternatives)

    return "\n".join(out)


async def trip_plan(
    destination: str,
    origin: str | None = None,
    arrive_by: str | None = None,
    depart_at: str | None = None,
    client=None,
    user_id: str | None = None,
) -> str:
    """Plan a public-transport journey with real-time legs, and rank the options.

    Uses TfNSW's trip planner rather than Google's, because the legs come back
    with live departure estimates rather than a timetable, and because asking
    for several journeys surfaces routes Maps does not offer.

    `arrive_by` / `depart_at` are ISO-8601. Give `arrive_by` when there is a
    meeting to be at; that is what makes a leave-by time meaningful.
    """
    if not TFNSW_API_KEY:
        return "Error: TFNSW_API_KEY is not set."

    origin_note = ""
    if not origin:
        if client is None or not user_id:
            return "Error: no origin given and no user context to look one up."
        resolved = await resolve_origin(client, user_id)
        if not resolved:
            return ("I don't know where you're starting from — no recent location "
                    "and no default saved place. Add one under Settings → Places.")
        origin = resolved["origin"]
        origin_note = f" (from {resolved['source']})"

    headers = {"Authorization": f"apikey {TFNSW_API_KEY}", "Accept": "application/json"}

    params = {
        "outputFormat": "rapidJSON",
        "coordOutputFormat": "EPSG:4326",
        "depArrMacro": "arr" if arrive_by else "dep",
        "type_origin": "any",
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

    # `http`, not `client`: `client` is the Supabase handle this function takes.
    async with httpx.AsyncClient() as http:
        try:
            res = await http.get(TRIP_URL, headers=headers, params=params, timeout=20.0)
            res.raise_for_status()
            data = res.json()
        except Exception as e:
            return f"Error fetching trip plan: {e}"

    journeys = data.get("journeys") or []
    if not journeys:
        return f"No public transport journeys found from {origin} to {destination}."

    ranked = rank_journeys([summarise_journey(j) for j in journeys])
    if not ranked:
        return f"TfNSW returned journeys for {destination} but none had usable times."
    return format_journeys(ranked, origin_note)
