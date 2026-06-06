"""Google Calendar executors: query, create, update."""
import asyncio
from datetime import datetime, timedelta, timezone

from googleapiclient.discovery import build
from google_auth import get_credentials


def _get_calendar_service():
    creds = get_credentials("calendar")
    return build("calendar", "v3", credentials=creds)


def _format_event_start(event: dict) -> str:
    start = event.get("start", {})
    raw = start.get("dateTime") or start.get("date", "")
    if not raw:
        return "Unknown time"
    if "T" in raw:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    return raw


# ── Query ──────────────────────────────────────────────────────
def _calendar_query_sync(query: str, days_ahead: int) -> str:
    days_ahead = max(1, min(days_ahead, 30))
    service = _get_calendar_service()

    now = datetime.now(timezone.utc)
    time_min = now.isoformat()
    time_max = (now + timedelta(days=days_ahead)).isoformat()

    result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            maxResults=50,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    events = result.get("items", [])
    query_lower = query.strip().lower()

    if query_lower:
        events = [
            e
            for e in events
            if query_lower in (e.get("summary") or "").lower()
        ]

    events = events[:20]

    if not events:
        return "No events found for the given criteria."

    cal_name = "Primary"
    try:
        cal = service.calendars().get(calendarId="primary").execute()
        cal_name = cal.get("summary", cal_name)
    except Exception:
        pass

    lines = []
    for event in events:
        title = event.get("summary") or "(No title)"
        when = _format_event_start(event)
        loc = event.get("location")
        loc_str = f" @ {loc}" if loc else ""
        attendees = event.get("attendees", [])
        att_str = f" with {len(attendees)} attendees" if attendees else ""
        lines.append(f"{when} — {title}{loc_str}{att_str} ({cal_name})")

    return "\n".join(lines)


# ── Create ─────────────────────────────────────────────────────
def _calendar_create_sync(
    summary: str,
    start: str,
    end: str,
    location: str = "",
    description: str = "",
    idempotency_key: str = "",
) -> str:
    service = _get_calendar_service()

    event_body: dict = {
        "summary": summary,
    }

    # Detect all-day vs timed event
    if "T" in start:
        event_body["start"] = {"dateTime": start, "timeZone": "Australia/Sydney"}
        event_body["end"] = {"dateTime": end, "timeZone": "Australia/Sydney"}
    else:
        event_body["start"] = {"date": start}
        event_body["end"] = {"date": end}

    if location:
        event_body["location"] = location
    if description:
        event_body["description"] = description

    if idempotency_key:
        event_body["iCalUID"] = f"ps-{idempotency_key}@projectsunday.local"

    created = service.events().insert(calendarId="primary", body=event_body).execute()
    event_link = created.get("htmlLink", "")
    return f"Event created: '{summary}' on {start}. Link: {event_link}"


# ── Update ─────────────────────────────────────────────────────
def _calendar_update_sync(
    event_id: str,
    summary: str = "",
    start: str = "",
    end: str = "",
    location: str = "",
    description: str = "",
) -> str:
    service = _get_calendar_service()

    # Fetch existing event
    event = service.events().get(calendarId="primary", eventId=event_id).execute()

    if summary:
        event["summary"] = summary
    if start:
        if "T" in start:
            event["start"] = {"dateTime": start, "timeZone": "Australia/Sydney"}
        else:
            event["start"] = {"date": start}
    if end:
        if "T" in end:
            event["end"] = {"dateTime": end, "timeZone": "Australia/Sydney"}
        else:
            event["end"] = {"date": end}
    if location:
        event["location"] = location
    if description:
        event["description"] = description

    updated = service.events().update(
        calendarId="primary", eventId=event_id, body=event
    ).execute()

    return f"Event updated: '{updated.get('summary')}'"



# ── Sync ───────────────────────────────────────────────────────
def _sync_calendar_events_sync(client) -> str:
    service = _get_calendar_service()
    now = datetime.now(timezone.utc)
    # Start from beginning of today UTC so past events today are included
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    time_min = today_start.isoformat()
    time_max = (now + timedelta(days=30)).isoformat()
    
    result = service.events().list(
        calendarId="primary",
        timeMin=time_min,
        timeMax=time_max,
        maxResults=500,
        singleEvents=True,
        orderBy="startTime",
    ).execute()
    
    events = result.get("items", [])
    if not events:
        return "No events to sync."
        
    cal_name = "Primary"
    try:
        cal = service.calendars().get(calendarId="primary").execute()
        cal_name = cal.get("summary", cal_name)
    except Exception:
        pass
        
    users_res = client.table("user_profile").select("user_id").execute()
    users = users_res.data or []
    
    upserted = 0
    for event in events:
        g_event_id = event.get("id")
        summary = event.get("summary") or "(No title)"
        start_str = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date")
        end_str = event.get("end", {}).get("dateTime") or event.get("end", {}).get("date")
        
        if not start_str or not end_str or not g_event_id:
            continue
            
        location = event.get("location", "")
        
        # Normalise all-day date strings to midnight UTC timestamptz
        if start_str and "T" not in start_str:
            start_str = f"{start_str}T00:00:00+00:00"
        if end_str and "T" not in end_str:
            end_str = f"{end_str}T00:00:00+00:00"
        
        for user in users:
            uid = user.get("user_id")
            if not uid: continue
            
            # Using uid + g_event_id for event_id to ensure both users get a row without conflict overwrites
            # if event_id is the unique column as per instructions.
            actual_event_id = f"{uid}_{g_event_id}"
            
            try:
                client.table("calendar_events").upsert({
                    "user_id": uid,
                    "event_id": actual_event_id,
                    "title": summary,
                    "start_time": start_str,
                    "end_time": end_str,
                    "calendar_name": cal_name,
                    "location": location,
                    "updated_at": datetime.now(timezone.utc).isoformat()
                }, on_conflict="event_id").execute()
                upserted += 1
            except Exception as e:
                print(f"[calendar_sync] failed for {uid} event {g_event_id}: {e}")
            
    return f"Synced {upserted} calendar events."

async def sync_calendar_events(client) -> str:
    return await asyncio.to_thread(_sync_calendar_events_sync, client)


# ── Async wrappers ─────────────────────────────────────────────
async def calendar_query(query: str = "", days_ahead: int = 7) -> str:
    return await asyncio.to_thread(_calendar_query_sync, query, days_ahead)


async def calendar_create(
    summary: str,
    start: str,
    end: str,
    location: str = "",
    description: str = "",
    idempotency_key: str = "",
) -> str:
    return await asyncio.to_thread(
        _calendar_create_sync, summary, start, end, location, description, idempotency_key
    )


async def calendar_update(
    event_id: str,
    summary: str = "",
    start: str = "",
    end: str = "",
    location: str = "",
    description: str = "",
) -> str:
    return await asyncio.to_thread(
        _calendar_update_sync, event_id, summary, start, end, location, description
    )
