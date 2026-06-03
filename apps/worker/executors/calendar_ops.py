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
        lines.append(f"{when} — {title} ({cal_name})")

    return "\n".join(lines)


# ── Create ─────────────────────────────────────────────────────
def _calendar_create_sync(
    summary: str,
    start: str,
    end: str,
    location: str = "",
    description: str = "",
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


# ── Async wrappers ─────────────────────────────────────────────
async def calendar_query(query: str = "", days_ahead: int = 7) -> str:
    return await asyncio.to_thread(_calendar_query_sync, query, days_ahead)


async def calendar_create(
    summary: str,
    start: str,
    end: str,
    location: str = "",
    description: str = "",
) -> str:
    return await asyncio.to_thread(
        _calendar_create_sync, summary, start, end, location, description
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
