import asyncio
import sys
from datetime import datetime, timezone, timedelta
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
from context.loader import fetch_and_cache_profile
from google_auth import verify_all_tokens
from scheduler import Scheduler
from jobs import morning_briefing, email_scan, news_fetch, meal_checkin, nightly_maintenance, calendar_prep, task_tracker, cold_storage_archive, send_daily_brief_for_all_users, send_daily_brief, sync_calendar_job
from executors.base import already_executed, mark_executed, set_status
from executors.notify_ops import push_approval, push
from executors.file_ops import file_read, file_list, file_write
from executors.profile_ops import update_profile
from executors.web_fetch import web_fetch
from executors.web_search_ops import web_search
from executors.travel_ops import travel_directions, transit_departures
from executors.calendar_ops import calendar_query, calendar_create, calendar_update
from executors.gmail_ops import gmail_search, gmail_draft, gmail_read_body, gmail_priority_scan
from executors.task_ops import task_create, task_update, task_list

# ── Tool executor registry ─────────────────────────────────────────────────
# Maps action_type string → async callable.
# To add a new tool: import the function and add one line here.
# Args are unpacked as kwargs: await TOOL_REGISTRY[tool](**args)
# For tools that need (client, user_id, **args), wrap them in a lambda below.

async def _schedule_reminder_executor(client: Client, user_id: str, message: str, remind_at_iso: str):
    await asyncio.to_thread(
        lambda: client.table("one_off_reminders").insert({
            "user_id": user_id,
            "remind_at": remind_at_iso,
            "message": message
        }).execute()
    )
    return f"Reminder scheduled for {remind_at_iso}"

def _make_registry(client_ref: list, user_id_ref: list) -> dict:
    """Build registry with late-bound client/user_id refs for tools that need them."""
    return {
        "file_read":           file_read,
        "file_list":           file_list,
        "file_write":          file_write,
        "web_fetch":           web_fetch,
        "web_search":          web_search,
        "travel_directions":   travel_directions,
        "transit_departures":  transit_departures,
        "calendar_query":      calendar_query,
        "calendar_create":     calendar_create,
        "calendar_update":     calendar_update,
        "gmail_search":        gmail_search,
        "gmail_draft":         gmail_draft,
        "gmail_read_body":     gmail_read_body,
        "gmail_priority_scan": gmail_priority_scan,
        "update_profile":      lambda **kw: update_profile(client_ref[0], user_id_ref[0], **kw),
        "task_create":         lambda **kw: task_create(client_ref[0], user_id=user_id_ref[0], **kw),
        "task_update":         lambda **kw: task_update(client_ref[0], user_id=user_id_ref[0], **kw),
        "task_list":           lambda **kw: task_list(client_ref[0], user_id=user_id_ref[0], **kw),
        "schedule_reminder":   lambda **kw: _schedule_reminder_executor(client_ref[0], user_id_ref[0], **kw),
    }

def _action_result_message(tool: str, result) -> str:
    return f"✅ Action {tool} completed: {result}"

async def _llm_confirmation(gemini_api_key: str, tool: str, args: dict, result) -> str:
    """Generate a natural confirmation message via LLM after an approved action executes.
    Falls back to _action_result_message if LLM call fails or result is already clean."""
    from google import genai
    from google.genai import types
    from config import GEMINI_MODEL
    # Don't burn a call for simple read-only tools — hardcoded is fine
    READ_ONLY = {"task_list", "calendar_query", "gmail_search", "gmail_read_body",
                 "web_search", "web_fetch", "file_read", "file_list"}
    if tool in READ_ONLY:
        return str(result) if isinstance(result, str) else _action_result_message(tool, result)
    try:
        prompt = (
            f"The user approved and executed this action: {tool}\n"
            f"Arguments: {args}\n"
            f"Result: {result}\n\n"
            "Write a single short, natural, friendly confirmation sentence for the user. "
            "Do not use bullet points. Do not repeat the raw data. "
            "Maximum 2 sentences. Start directly — no preamble."
        )
        ai_client = genai.Client(api_key=gemini_api_key)
        response = await asyncio.to_thread(
            lambda: ai_client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
            )
        )
        text = response.text.strip()
        return text if text else _action_result_message(tool, result)
    except Exception as e:
        print(f"[worker] second-pass LLM failed for {tool}: {e}")
        return _action_result_message(tool, result)

def get_client() -> Client:
    return create_client(SUPABASE_URL, get_service_role_key())

async def execute_action(client: Client, action: dict, gemini_api_key: str = ""):
    action_id = action["id"]
    user_id = action.get("user_id")
    idempotency_key = str(action.get("idempotency_key", action_id))
    tool = action["action_type"]
    args = action.get("payload", {})

    if already_executed(idempotency_key):
        print(f"[worker] skipping already-executed {action_id}")
        return

    # Atomic claim: update to 'processing' ONLY if status is 'approved'.
    # Auto-tier rows are inserted as status='pending', approved=True — they get
    # set to 'approved' by the insert path in handle_message before reaching here.
    # Approve-tier rows arrive here only after the user clicks Approve in the UI
    # which sets status='approved'.
    claim = await asyncio.to_thread(
        lambda: client.table("action_queue")
        .update({"status": "processing"})
        .eq("id", action_id)
        .eq("status", "approved")
        .execute()
    )

    if not claim.data:
        print(f"[worker] {action_id} could not be claimed (not in 'approved' state) — skipping")
        return

    # Only mark the idempotency key AFTER we've confirmed the row is approved
    # and we've atomically claimed it. This prevents burning the key on
    # unapproved or already-claimed rows.
    mark_executed(idempotency_key)

    try:
        # Build registry with this action's client and user_id bound
        _c = [client]
        _u = [user_id]
        registry = _make_registry(_c, _u)
        
        if tool not in registry:
            raise NotImplementedError(f"Executor for '{tool}' not yet implemented")
            
        # Special-case: update_profile needs section + content validated
        if tool == "update_profile":
            section = args.get("section", "General")
            content = args.get("content", "")
            if not section or not content:
                result = "Error: section and content are required."
            else:
                result = await registry[tool](section=section, content=content)
        else:
            result = await registry[tool](**args)

        await set_status(client, action_id, "executed")
        confirmation_msg = await _llm_confirmation(gemini_api_key, tool, args, result)
        await asyncio.to_thread(
            lambda: client.table("messages").insert({
                "user_id": user_id,
                "role": "assistant",
                "content": confirmation_msg,
                "model_used": "gemini"
            }).execute()
        )

    except Exception as e:
        print(f"[worker] executor error {action_id}: {e}")
        await set_status(client, action_id, "failed", {"error": str(e)})

async def handle_message(client: Client, message: dict, history: list, user_id: str) -> bool:
    content = message.get("content", "")
    if not content or message.get("role") != "user":
        return False
    print(f"[router] routing: {content[:60]}")
    try:
        result = await route(client, content, history, GEMINI_API_KEY, user_id)
    except Exception as e:
        print(f"[router] error: {e}")
        error_msg = str(e)
        if "503" in error_msg or "high demand" in error_msg.lower():
            friendly_msg = "The AI provider is currently experiencing high demand. Please try again in a moment."
        else:
            friendly_msg = f"Sorry, I couldn't process that message: {e}"
            
        await asyncio.to_thread(
            lambda: client.table("messages").insert({
                "user_id": user_id,
                "role": "assistant",
                "content": friendly_msg,
                "model_used": "system",
            }).execute()
        )
        return False

    model_used = result.get("model_used", "system")

    if result["type"] == "text":
        await asyncio.to_thread(
            lambda: client.table("messages").insert({
                "user_id": user_id,
                "role": "assistant",
                "content": result["content"],
                "model_used": model_used
            }).execute()
        )
        return True

    if result["type"] == "tool_call":
        tool = result["tool"]
        tier = result["tier"]
        inserted = await asyncio.to_thread(
            lambda: client.table("action_queue").insert({
                "user_id": user_id,
                "action_type": tool,
                "payload": result["args"],
                "tier": tier,
                "status": "approved" if tier == "auto" else "awaiting_approval",
                "approved": True if tier == "auto" else None
            }).execute()
        )
        
        if tier != "auto":
            await push_approval(action_type=tool, summary=str(result.get("args", "")))

        if tier == "approve":
            await asyncio.to_thread(
                lambda: client.table("messages").insert({
                    "user_id": user_id,
                    "role": "assistant",
                    "content": f"I've suggested an action for your approval: {tool}. Check the Approvals tab.",
                    "model_used": "system"
                }).execute()
            )

        if tier == "auto" and inserted.data:
            await execute_action(client, inserted.data[0], GEMINI_API_KEY)
        return True

    return False

async def poll_approved(client: Client, gemini_api_key: str):
    while True:
        try:
            await asyncio.sleep(APPROVAL_POLL_INTERVAL_SECONDS)
            rows = await asyncio.to_thread(
                lambda: client.table("action_queue").select("*").eq("status", "approved").execute()
            )
            found = rows.data or []
            print(f"[poll] checking approved queue — {len(found)} rows")
            for row in found:
                await execute_action(client, row, gemini_api_key)
        except Exception as e:
            print(f"[poll] error: {e}", flush=True)

async def reap_stale_processing(client: Client):
    """Every 5 minutes, find action_queue rows stuck in 'processing' for >10 min
    and reset them to 'approved' so the worker can retry via idempotency key."""
    while True:
        try:
            await asyncio.sleep(300)  # 5 minutes
            cutoff = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
            stale = await asyncio.to_thread(
                lambda: client.table("action_queue")
                .update({"status": "approved"})
                .eq("status", "processing")
                .lt("updated_at", cutoff)
                .execute()
            )
            reaped = len(stale.data) if stale.data else 0
            if reaped > 0:
                print(f"[reaper] Reset {reaped} stale processing row(s) back to 'approved'")
        except Exception as e:
            print(f"[reaper] error: {e}", flush=True)

async def poll_profile_updates(client: Client):
    last_updated_at = None
    while True:
        try:
            await asyncio.sleep(10)
            res = await asyncio.to_thread(
                lambda: client.table("user_profile").select("updated_at").limit(1).execute()
            )
            if res.data:
                current_updated_at = res.data[0].get("updated_at")
                if last_updated_at is not None and current_updated_at != last_updated_at:
                    print(f"[poll] profile update detected, reloading...")
                    await asyncio.to_thread(lambda: fetch_and_cache_profile(client))
                last_updated_at = current_updated_at
        except Exception as e:
            print(f"[poll] profile check error: {e}", flush=True)

async def poll_reminders(client: Client):
    """Poll for reminders that are due and send them."""
    # Note: push() currently sends to a global NTFY_TOPIC.
    # In a multi-user environment, this needs to be updated to a per-user notification channel.
    while True:
        try:
            await asyncio.sleep(60)
            now_iso = datetime.now(timezone.utc).isoformat()
            
            profiles = await asyncio.to_thread(lambda: client.table("user_profile").select("user_id").execute())
            for row in (profiles.data or []):
                uid = row.get("user_id")
                if not uid:
                    continue
                    
                res = await asyncio.to_thread(
                    lambda u=uid: client.table("one_off_reminders")
                    .select("*")
                    .eq("user_id", u)
                    .eq("fired", False)
                    .lte("remind_at", now_iso)
                    .execute()
                )
                
                for reminder in (res.data or []):
                    msg = reminder["message"]
                    
                    await push(title="Reminder", body=msg, priority="high", tags=["alarm_clock"])
                    
                    await asyncio.to_thread(
                        lambda r=reminder, u=uid: client.table("messages").insert({
                            "user_id": u,
                            "role": "assistant",
                            "content": f"⏰ **Reminder**: {r['message']}",
                            "model_used": "system"
                        }).execute()
                    )
                    
                    await asyncio.to_thread(
                        lambda r=reminder: client.table("one_off_reminders").update({"fired": True}).eq("id", r["id"]).execute()
                    )
        except Exception as e:
            print(f"[poll_reminders] error: {e}", flush=True)

async def main():
    print("[worker] Project Sunday worker starting...")
    client = get_client()
    await asyncio.to_thread(lambda: fetch_and_cache_profile(client))

    # Start profile poll loop
    def _on_profile_poll_done(task):
        if task.exception():
            print(f"[poll] profile task died: {task.exception()}", flush=True)
    profile_poll_task = asyncio.create_task(poll_profile_updates(client))
    profile_poll_task.add_done_callback(_on_profile_poll_done)

    # Verify Google OAuth tokens on startup
    token_status = verify_all_tokens()
    for service, valid in token_status.items():
        status = "✓" if valid else "✗ (re-auth needed)"
        print(f"[worker] Google {service}: {status}")

    # Verify Ollama connectivity and list models
    try:
        from ollama import AsyncClient as OllamaClient
        from config import OLLAMA_MODEL, OLLAMA_HOST
        ollama_client = OllamaClient(host=OLLAMA_HOST)
        models_resp = await ollama_client.list()
        model_names = [m.get("name", m.get("model", "?")) for m in (models_resp.get("models") or [])]
        print(f"[worker] Ollama models available: {model_names}")
        if OLLAMA_MODEL in model_names:
            print(f"[worker] Ollama {OLLAMA_MODEL}: ✓")
        else:
            print(f"[worker] ⚠ Ollama {OLLAMA_MODEL} not found in {model_names}")
    except Exception as e:
        print(f"[worker] Ollama: ✗ (not reachable: {e})")

    # Start heartbeat
    asyncio.create_task(run_heartbeat(client, HEARTBEAT_INTERVAL_SECONDS))

    # Start approval poll loop
    def _on_poll_done(task):
        if task.exception():
            print(f"[poll] task died: {task.exception()}", flush=True)
    poll_task = asyncio.create_task(poll_approved(client, GEMINI_API_KEY))
    poll_task.add_done_callback(_on_poll_done)

    # Start stale processing reaper (Fix 4)
    def _on_reaper_done(task):
        if task.exception():
            print(f"[reaper] task died: {task.exception()}", flush=True)
    reaper_task = asyncio.create_task(reap_stale_processing(client))
    reaper_task.add_done_callback(_on_reaper_done)

    # Start scheduler
    sched = Scheduler(client, GEMINI_API_KEY)
    sched.register_handler("morning_briefing", morning_briefing)
    sched.register_handler("email_scan", email_scan)
    sched.register_handler("news_fetch", news_fetch)
    sched.register_handler("meal_checkin", meal_checkin)
    sched.register_handler("nightly_maintenance", nightly_maintenance)
    sched.register_handler("calendar_prep", calendar_prep)
    sched.register_handler("task_tracker", task_tracker)
    sched.register_handler("cold_storage_archive", cold_storage_archive)
    sched.register_handler("daily_brief", send_daily_brief_for_all_users)
    sched.register_handler("sync_calendar", sync_calendar_job)
    asyncio.create_task(sched.run())

    # Start reminders poll loop
    def _on_reminders_done(task):
        if task.exception():
            print(f"[poll_reminders] task died: {task.exception()}", flush=True)
    reminders_task = asyncio.create_task(poll_reminders(client))
    reminders_task.add_done_callback(_on_reminders_done)

    print("[worker] ready. Listening for messages, approvals, and scheduled jobs.")

    # Ensure sync_calendar is registered as a 15-minute job
    try:
        await asyncio.to_thread(
            lambda: client.table("scheduled_jobs").upsert({
                "job_name": "sync_calendar",
                "cron_expr": "*/15 * * * *",
                "timezone": "UTC",
                "config": {"description": "Sync Google Calendar events to Supabase"}
            }).execute()
        )
    except Exception as e:
        print(f"[worker] Failed to register sync_calendar job: {e}")

    # Run calendar sync on startup
    asyncio.create_task(sync_calendar_job(client, GEMINI_API_KEY))

    # On startup: send today's brief if not already sent
    import datetime as dt
    try:
        today = dt.date.today().isoformat()
        profiles = await asyncio.to_thread(lambda: client.table("user_profile").select("user_id").execute())
        for row in (profiles.data or []):
            user_id = row.get("user_id")
            if user_id:
                existing = await asyncio.to_thread(
                    lambda u=user_id: client.table("messages")
                    .select("id")
                    .eq("user_id", u)
                    .eq("model_used", "system")
                    .gte("created_at", today)
                    .limit(1).execute()
                )
                if not existing.data:
                    await send_daily_brief(client, user_id)
    except Exception as e:
        print(f"[worker] Failed startup brief check: {e}")

    retries = 0
    last_processed_ids = {} # per user_id
    message_count = 0

    # Record startup time — only process messages created after this point
    startup_watermark = datetime.now(timezone.utc).isoformat()

    while True:
        try:
            # Poll latest 10 messages across all users
            all_msgs = await asyncio.to_thread(
                lambda: client.table("messages").select("*").gte("created_at", startup_watermark).order("created_at", desc=True).limit(10).execute()
            )

            if all_msgs.data:
                # Process oldest to newest among the newly found
                for latest in reversed(all_msgs.data):
                    if latest["role"] != "user":
                        continue
                    
                    uid = latest.get("user_id")
                    if not uid:
                        continue
                        
                    if latest["id"] != last_processed_ids.get(uid):
                        # Claim the message — only process if claim succeeds (no other brain claimed it)
                        claim_res = await asyncio.to_thread(
                            lambda msg=latest: client.table("messages")
                            .update({"claimed_by": "mac"})
                            .eq("id", msg["id"])
                            .is_("claimed_by", "null")
                            .execute()
                        )
                        if not claim_res.data:
                            # Another brain already claimed this — skip
                            continue

                        history = await asyncio.to_thread(
                            lambda u=uid: client.table("messages").select("role,content").eq("user_id", u).order("created_at", desc=True).limit(20).execute()
                        )
                        history_list = list(reversed(history.data or []))
                        if await handle_message(client, latest, history_list, uid):
                            message_count += 1
                            await maybe_summarise(client, GEMINI_API_KEY, message_count, uid)
                        last_processed_ids[uid] = latest["id"]

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
                    await asyncio.to_thread(
                        lambda: client.table("messages").insert({
                            "role": "assistant",
                            "content": "Worker crashed and could not reconnect. Restart required.",
                            "model_used": "system"
                        }).execute()
                    )
                except Exception:
                    pass
                sys.exit(1)
            await asyncio.sleep(wait)

if __name__ == "__main__":
    asyncio.run(main())
