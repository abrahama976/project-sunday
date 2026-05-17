import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

_WORKER_DIR = Path(__file__).resolve().parent.parent
_CREDENTIALS_PATH = _WORKER_DIR / "credentials.json"
_TOKEN_PATH = _WORKER_DIR / "token_calendar.json"
_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


def _get_credentials() -> Credentials:
    creds = None
    if _TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(_TOKEN_PATH), _SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(_CREDENTIALS_PATH), _SCOPES
            )
            creds = flow.run_local_server(port=0)
        _TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")

    return creds


def _get_calendar_service():
    creds = _get_credentials()
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


async def calendar_query(query: str = "", days_ahead: int = 7) -> str:
    return await asyncio.to_thread(_calendar_query_sync, query, days_ahead)
