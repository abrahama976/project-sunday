import asyncio
import sys
from supabase import create_client, Client
from auth import get_service_role_key
from config import (
    SUPABASE_URL, GEMINI_API_KEY,
    HEARTBEAT_INTERVAL_SECONDS,
    WORKER_RECONNECT_MAX_RETRIES,
    WORKER_RECONNECT_BACKOFF_BASE_SECONDS,
    APPROVAL_POLL_INTERVAL_SECONDS,
)
from heartbeat import run_heartbeat
from router import route
from summariser import maybe_summarise
from context.loader import load_profile
from executors.base import already_executed, mark_executed, set_status
from executors.file_ops import file_read, file_list
from executors.profile_ops import update_profile
from executors.web_fetch import web_fetch
from executors.calendar_ops import calendar_query
from executors.gmail_ops import gmail_search, gmail_draft

def get_client() -> Client:
    return create_client(SUPABASE_URL, get_service_role_key())

async def execute_action(client: Client, action: dict):
    action_id = action["id"]
    idempotency_key = str(action.get("idempotency_key", action_id))
    tool = action["action_type"]
    args = action.get("payload", {})

    if already_executed(idempotency_key):
        print(f"[worker] skipping already-executed {action_id}")
        return

    row = client.table("action_queue").select("approved,status,tier").eq("id", action_id).single().execute()
    if not row.data:
        print(f"[worker] action {action_id} not found — skipping")
        return

    db_approved = row.data.get("approved")
    db_status = row.data.get("status")
    db_tier = row.data.get("tier", "approve")

    if db_tier != "auto" and not db_approved:
        print(f"[worker] {action_id} not approved — skipping")
        return
    if db_status in ("executed", "failed", "denied"):
        print(f"[worker] {action_id} already {db_status} — skipping")
        return

    await set_status(client, action_id, "executing")
    mark_executed(idempotency_key)

    try:
        if tool == "file_read":
            result = await file_read(**args)
        elif tool == "file_list":
            result = await file_list(**args)
        elif tool == "update_profile":
            result = await update_profile(**args)
        elif tool == "web_fetch":
            result = await web_fetch(**args)
        elif tool == "calendar_query":
            result = await calendar_query(**args)
        elif tool == "gmail_search":
            result = await gmail_search(**args)
        elif tool == "gmail_draft":
            result = await gmail_draft(**args)
        else:
            raise NotImplementedError(f"Executor for '{tool}' not yet implemented")

        await set_status(client, action_id, "executed")
        client.table("messages").insert({
            "role": "assistant",
            "content": result,
            "model_used": "gemini"
        }).execute()

    except Exception as e:
        print(f"[worker] executor error {action_id}: {e}")
        await set_status(client, action_id, "failed", {"error": str(e)})

async def handle_message(client: Client, message: dict, history: list) -> bool:
    content = message.get("content", "")
    if not content or message.get("role") != "user":
        return False
    print(f"[router] routing: {content[:60]}")
    try:
        result = await route(content, history, GEMINI_API_KEY)
    except Exception as e:
        print(f"[router] error: {e}")
        client.table("messages").insert({
            "role": "assistant",
            "content": f"Sorry, I couldn't process that message: {e}",
            "model_used": "system",
        }).execute()
        return False

    if result["type"] == "text":
        client.table("messages").insert({
            "role": "assistant",
            "content": result["content"],
            "model_used": "gemini"
        }).execute()
        return True

    if result["type"] == "tool_call":
        tool = result["tool"]
        tier = result["tier"]
        inserted = client.table("action_queue").insert({
            "action_type": tool,
            "payload": result["args"],
            "tier": tier,
            "status": "pending",
            "approved": True if tier == "auto" else None
        }).execute()

        if tier == "auto" and inserted.data:
            await execute_action(client, inserted.data[0])
        return True

    return False

async def poll_approved(client: Client):
    while True:
        await asyncio.sleep(APPROVAL_POLL_INTERVAL_SECONDS)
        try:
            rows = client.table("action_queue").select("*").eq("approved", True).in_("status", ["pending", "approved"]).execute()
            for row in (rows.data or []):
                await execute_action(client, row)
        except Exception as e:
            print(f"[poll] error: {e}")

async def main():
    print("[worker] Project Sunday worker starting...")
    load_profile()
    client = get_client()

    asyncio.create_task(run_heartbeat(client, HEARTBEAT_INTERVAL_SECONDS))
    asyncio.create_task(poll_approved(client))

    print("[worker] ready. Listening for messages and approvals.")

    retries = 0
    last_processed_id = None
    message_count = 0

    while True:
        try:
            all_msgs = client.table("messages").select("*").order("created_at", desc=True).limit(2).execute()

            if all_msgs.data and all_msgs.data[0]["role"] == "user":
                latest = all_msgs.data[0]
                if latest["id"] != last_processed_id:
                    history = client.table("messages").select("role,content").order("created_at", desc=True).limit(20).execute()
                    history_list = list(reversed(history.data or []))
                    if await handle_message(client, latest, history_list):
                        message_count += 1
                        await maybe_summarise(client, GEMINI_API_KEY, message_count)
                    last_processed_id = latest["id"]

            await asyncio.sleep(2)
            retries = 0

        except KeyboardInterrupt:
            print("[worker] shutting down.")
            sys.exit(0)
        except Exception as e:
            retries += 1
            wait = WORKER_RECONNECT_BACKOFF_BASE_SECONDS ** retries
            print(f"[worker] error (retry {retries}/{WORKER_RECONNECT_MAX_RETRIES}): {e}")
            if retries > WORKER_RECONNECT_MAX_RETRIES:
                try:
                    client.table("messages").insert({
                        "role": "assistant",
                        "content": "Worker crashed and could not reconnect. Restart required.",
                        "model_used": "system"
                    }).execute()
                except Exception:
                    pass
                sys.exit(1)
            await asyncio.sleep(wait)

if __name__ == "__main__":
    asyncio.run(main())
