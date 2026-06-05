"""Push notifications via ntfy.sh."""
import httpx
from config import NTFY_URL
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
