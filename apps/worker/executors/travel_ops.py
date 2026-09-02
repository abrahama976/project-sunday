import httpx
import json
from config import GOOGLE_MAPS_API_KEY, TFNSW_API_KEY
from utils import resolve_origin


async def travel_directions(
    destination: str,
    origin: str | None = None,
    mode: str = "transit",
    client=None,
    user_id: str | None = None,
) -> str:
    """Get directions from Google Maps API.

    `origin` is optional. Left out, it resolves to your live position when the
    phone has reported recently, else your default saved place — so "when do I
    need to leave for X?" is answerable without the model stopping to ask where
    you are, which is what it did before saved places existed.
    """
    if not GOOGLE_MAPS_API_KEY:
        return "Error: GOOGLE_MAPS_API_KEY is not set."

    origin_note = ""
    if not origin:
        if client is None or not user_id:
            return ("Error: no origin given and no user context to look one up. "
                    "Say where you are starting from.")
        resolved = await resolve_origin(client, user_id)
        if not resolved:
            return ("I don't know where you're starting from — no recent location "
                    "and no default saved place. Add one under Settings → Places, "
                    "or tell me the starting point.")
        origin = resolved["origin"]
        origin_note = f" (from {resolved['source']})"

    url = "https://maps.googleapis.com/maps/api/directions/json"
    params = {
        "origin": origin,
        "destination": destination,
        "mode": mode,
        "key": GOOGLE_MAPS_API_KEY
    }
    
    # Named `http`, not `client`: `client` is the Supabase handle this function
    # now takes, and shadowing it here would break the next person who reaches
    # for it inside this block.
    async with httpx.AsyncClient() as http:
        try:
            response = await http.get(url, params=params)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            return f"Error fetching directions: {e}"
            
    if data.get("status") != "OK":
        return f"Google Maps API Error: {data.get('status', 'Unknown')} - {data.get('error_message', '')}"
        
    try:
        route = data["routes"][0]["legs"][0]
        distance = route["distance"]["text"]
        duration = route["duration"]["text"]
        start_addr = route["start_address"]
        end_addr = route["end_address"]
        
        output = [f"Directions: {start_addr} -> {end_addr}{origin_note}"]
        output.append(f"Mode: {mode.capitalize()} | Distance: {distance} | ETA: {duration}")
        output.append("Steps:")
        
        for idx, step in enumerate(route["steps"], 1):
            # Clean HTML from instructions
            import re
            instructions = re.sub(r'<[^>]+>', ' ', step["html_instructions"])
            instructions = re.sub(r'\s+', ' ', instructions).strip()
            output.append(f"  {idx}. {instructions} ({step['duration']['text']})")
            
        return "\n".join(output)
    except Exception as e:
        return f"Error parsing directions: {e}"


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
        
        # Real-time departure if available, otherwise scheduled
        dep_time = event.get("departureTimeEstimated") or event.get("departureTimePlanned")
        if dep_time:
            # The time is usually in format "2023-10-27T14:30:00Z"
            import dateutil.parser
            from zoneinfo import ZoneInfo
            dt = dateutil.parser.isoparse(dep_time).astimezone(ZoneInfo("Australia/Sydney"))
            time_str = dt.strftime("%I:%M %p")
        else:
            time_str = "Unknown time"
            
        platform = event.get("location", {}).get("properties", {}).get("platform", "")
        platform_str = f" (Plat {platform})" if platform else ""
        
        output.append(f"- {time_str}: {mode_str} to {dest}{platform_str}")
        
    return "\n".join(output)
