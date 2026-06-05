"""Gmail executors: search, draft, read_body, priority_scan."""
import asyncio
import base64
from datetime import datetime, timezone
from email.mime.text import MIMEText

from googleapiclient.discovery import build
from google_auth import get_credentials


def _get_gmail_service():
    creds = get_credentials("gmail")
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


def _extract_plain_text(payload: dict, max_chars: int = 4000) -> str:
    """Recursively extract plain text body from Gmail message payload."""
    mime_type = payload.get("mimeType", "")

    # Direct text/plain part
    if mime_type == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            text = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            return text[:max_chars]

    # Multipart — recurse into parts
    parts = payload.get("parts", [])
    for part in parts:
        result = _extract_plain_text(part, max_chars)
        if result:
            return result

    # Fallback: try text/html if no plain text found
    if mime_type == "text/html":
        data = payload.get("body", {}).get("data", "")
        if data:
            html = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            # Strip HTML tags (rough, but sufficient for summarisation)
            import re
            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"\s+", " ", text).strip()
            return text[:max_chars]

    for part in parts:
        if part.get("mimeType", "") == "text/html":
            result = _extract_plain_text(part, max_chars)
            if result:
                return result

    return ""


# ── Search ─────────────────────────────────────────────────────
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


# ── Draft ──────────────────────────────────────────────────────
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


# ── Read Body ──────────────────────────────────────────────────
def _gmail_read_body_sync(message_id: str) -> str:
    """Fetch the full body of a Gmail message, return plain text truncated to 4000 chars."""
    service = _get_gmail_service()

    msg = (
        service.users()
        .messages()
        .get(userId="me", id=message_id, format="full")
        .execute()
    )

    headers = msg.get("payload", {}).get("headers", [])
    subject = _header(headers, "Subject") or "(No subject)"
    sender = _header(headers, "From") or "Unknown"
    body_text = _extract_plain_text(msg.get("payload", {}))

    if not body_text:
        return f"From: {sender}\nSubject: {subject}\n\n(No readable text body found)"

    return f"From: {sender}\nSubject: {subject}\n\n{body_text}"


# ── Priority Scan ──────────────────────────────────────────────
def _gmail_priority_scan_sync(max_results: int = 20) -> str:
    """Scan recent unread important emails, return structured summary."""
    max_results = max(1, min(max_results, 20))
    service = _get_gmail_service()

    # Query 1: Important + unread (Gmail's own importance marker)
    query = "is:unread is:important -category:promotions -category:social"

    listed = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=max_results)
        .execute()
    )

    message_ids = []
    seen = set()
    for m in listed.get("messages", []):
        if m["id"] not in seen:
            seen.add(m["id"])
            message_ids.append(m["id"])

    if not message_ids:
        return "No unread important emails."

    results = []
    for msg_id in message_ids:
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=msg_id, format="metadata",
                 metadataHeaders=["From", "Subject", "Date"])
            .execute()
        )
        headers = msg.get("payload", {}).get("headers", [])
        results.append({
            "id": msg_id,
            "from": _header(headers, "From"),
            "subject": _header(headers, "Subject") or "(No subject)",
            "date": _header(headers, "Date") or _format_internal_date(msg.get("internalDate", "")),
            "snippet": msg.get("snippet", ""),
        })

    import json
    return json.dumps(results, indent=2)


# ── Async wrappers ─────────────────────────────────────────────
async def gmail_search(query: str, max_results: int = 10) -> str:
    return await asyncio.to_thread(_gmail_search_sync, query, max_results)


async def gmail_draft(to: str, subject: str, body: str) -> str:
    return await asyncio.to_thread(_gmail_draft_sync, to, subject, body)


async def gmail_read_body(message_id: str) -> str:
    return await asyncio.to_thread(_gmail_read_body_sync, message_id)


async def gmail_priority_scan(max_results: int = 5) -> str:
    return await asyncio.to_thread(_gmail_priority_scan_sync, max_results)
