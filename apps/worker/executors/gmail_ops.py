import asyncio
import base64
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

_WORKER_DIR = Path(__file__).resolve().parent.parent
_CREDENTIALS_PATH = _WORKER_DIR / "credentials.json"
_TOKEN_PATH = _WORKER_DIR / "token_gmail.json"
_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]


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


def _get_gmail_service():
    creds = _get_credentials()
    return build("gmail", "v1", credentials=creds)


def _header(headers: list[dict], name: str) -> str:
    name_lower = name.lower()
    for h in headers:
        if h.get("name", "").lower() == name_lower:
            return h.get("value", "")
    return ""


def _format_internal_date(internal_date: str) -> str:
    try:
        ts = int(internal_date) / 1000
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return "Unknown date"


def _gmail_search_sync(query: str, max_results: int) -> str:
    max_results = max(1, min(max_results, 10))
    service = _get_gmail_service()

    listed = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=max_results)
        .execute()
    )

    message_ids = [m["id"] for m in listed.get("messages", [])]
    if not message_ids:
        return "No emails found matching that query."

    lines = []
    for msg_id in message_ids:
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=msg_id, format="metadata", metadataHeaders=["From", "Subject", "Date"])
            .execute()
        )
        headers = msg.get("payload", {}).get("headers", [])
        date = _header(headers, "Date") or _format_internal_date(msg.get("internalDate", ""))
        sender = _header(headers, "From") or "Unknown"
        subject = _header(headers, "Subject") or "(No subject)"
        lines.append(f"{date} | {sender} | {subject}")

    return "\n".join(lines)


def _gmail_draft_sync(to: str, subject: str, body: str) -> str:
    service = _get_gmail_service()

    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    service.users().drafts().create(
        userId="me",
        body={"message": {"raw": raw}},
    ).execute()

    return f"Draft created: '{subject}' to {to}"


async def gmail_search(query: str, max_results: int = 10) -> str:
    return await asyncio.to_thread(_gmail_search_sync, query, max_results)


async def gmail_draft(to: str, subject: str, body: str) -> str:
    return await asyncio.to_thread(_gmail_draft_sync, to, subject, body)
