"""Telling the user something happened — in the app, and optionally by push.

Two channels, and the difference matters. `notify()` writes a row the bell
reads: private, durable, and readable later. `push()` goes to ntfy, which is a
PUBLIC topic — anyone who knows `sunday-…` can read every message on it.

So the rule this module encodes: **content goes in the app, the push is a
doorbell.** Anything specific about where the user is going, who they are
meeting or what is in their calendar belongs in `notify()` only.
"""
import asyncio

import httpx
from config import NTFY_URL


async def notify(client, user_id: str, title: str, body: str = "",
                 also_push: bool = False, priority: str = "default") -> bool:
    """Write a notification the bell will show. Never raises.

    The `notifications` table has been read by the notification panel since it
    was built and written by nothing, so the bell has only ever shown pending
    approvals. This is the missing writer.

    Never raises, for the same reason `log_turn` does not: a travel alert that
    fails to record must not take down the job that produced it. Losing the
    notification is bad; losing the work is worse.

    `also_push` rings the doorbell without saying anything specific — the title
    is deliberately not forwarded, because the topic is public.
    """
    if client is None or not user_id or not title:
        return False
    try:
        await asyncio.to_thread(
            lambda: client.table("notifications").insert({
                "user_id": user_id, "title": title, "body": body or None,
            }).execute()
        )
    except Exception as exc:                       # noqa: BLE001
        print(f"[notify_ops] could not record notification: {exc}")
        return False

    if also_push:
        await push(
            title="Sunday has something for you",
            body="Open the app to see it.",
            priority=priority, tags=["bell"],
        )
    return True
async def push(title: str, body: str = "", priority: str = "default", tags: list[str] | None = None) -> bool:
    """Send a push notification. Priority: min|low|default|high|urgent."""
    if not NTFY_URL:
        print("[notify_ops] NTFY_URL not configured — skipping push")
        return False
    headers = {"Title": title, "Priority": priority, "Content-Type": "text/plain"}
    if tags:
        headers["Tags"] = ",".join(tags)
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            r = await client.post(NTFY_URL, content=body.encode(), headers=headers)
            return r.status_code == 200
    except Exception as exc:
        print(f"[notify_ops] push failed: {exc}")
        return False
async def push_approval(action_type: str, summary: str = "") -> bool:
    return await push(
        title=f"Sunday: action waiting — {action_type.replace('_', ' ')}",
        body=summary or "Open the app to review and approve.",
        priority="high", tags=["bell", "white_check_mark"],
    )
async def push_brief_ready() -> bool:
    return await push(
        title="Sunday: your morning brief is ready",
        body="Open the app to read today's brief.",
        priority="default", tags=["sunny", "calendar"],
    )
