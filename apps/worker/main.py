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
    TOOL_TIER_MAP,
)
from heartbeat import run_heartbeat
from router import route_special, degraded_chat
from agent_loop import run_agent_loop
from summariser import maybe_summarise
from context.loader import fetch_and_cache_profile, fetch_and_cache_directives
from google_auth import verify_all_tokens
from scheduler import Scheduler
from jobs import morning_briefing, email_scan, meal_checkin, nightly_maintenance, calendar_prep, task_tracker, cold_storage_archive, send_daily_brief_job, send_daily_brief, sync_calendar_job
from executors.base import set_status
from executors.notify_ops import push_approval, push
from executors.file_ops import file_read, file_list, file_write
from executors.profile_ops import update_profile
from executors.brain_ops import brain_learn
from executors.web_fetch import web_fetch
from utils import generate_with_retry, resolve_user
from executors.web_search_ops import web_search
from executors.travel_ops import travel_directions, transit_departures, trip_plan
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
        # Bound like the other context-aware tools: without the client and
        # user_id it cannot resolve an omitted origin.
        "travel_directions":   lambda **kw: travel_directions(
            client=client_ref[0], user_id=user_id_ref[0], **kw),
        "transit_departures":  transit_departures,
        "trip_plan":           lambda **kw: trip_plan(
            client=client_ref[0], user_id=user_id_ref[0], **kw),
        "calendar_query":      calendar_query,
        "calendar_create":     calendar_create,
        "calendar_update":     calendar_update,
        "gmail_search":        gmail_search,
        "gmail_draft":         gmail_draft,
        "gmail_read_body":     gmail_read_body,
        "gmail_priority_scan": gmail_priority_scan,
        "update_profile":      lambda **kw: update_profile(client_ref[0], user_id_ref[0], **kw),
        "brain_learn":         lambda **kw: brain_learn(client_ref[0], user_id_ref[0], **kw),
        "task_create":         lambda **kw: task_create(client_ref[0], user_id=user_id_ref[0], **kw),
        "task_update":         lambda **kw: task_update(client_ref[0], user_id=user_id_ref[0], **kw),
        "task_list":           lambda **kw: task_list(client_ref[0], user_id=user_id_ref[0], **kw),
        "schedule_reminder":   lambda **kw: _schedule_reminder_executor(client_ref[0], user_id_ref[0], **kw),
    }

def _action_result_message(tool: str, args: dict, result) -> str:
    templates = {
        "calendar_create":   lambda a, r: f"✓ Added '{a.get('summary', '')}' to your calendar for {a.get('start', '')}.",
        "calendar_update":   lambda a, r: f"✓ Calendar event updated.",
        "gmail_draft":       lambda a, r: f"✓ Draft saved: '{a.get('subject', '')}' to {a.get('to', '')}.",
        "task_create":       lambda a, r: f"✓ Task '{a.get('name', '')}' created.",
        "task_update":       lambda a, r: f"✓ Task updated.",
        "update_profile":    lambda a, r: f"✓ Profile updated: {a.get('section', '')}.",
        # Uses the executor's own return: it reports whether this superseded an
        # existing rule, which is the part worth seeing.
        "brain_learn":       lambda a, r: f"🧠 {r}",
        "schedule_reminder": lambda a, r: f"✓ Reminder set for {a.get('remind_at_iso', '')}.",
    }
    fn = templates.get(tool)
    if fn:
        try:
            return fn(args, result)
        except Exception:
            pass
    return f"✅ {tool} completed."

def get_client() -> Client:
    return create_client(SUPABASE_URL, get_service_role_key())

async def execute_action(client: Client, action: dict):
    action_id = action["id"]
    user_id = action.get("user_id")
    idempotency_key = str(action.get("idempotency_key", action_id))
    tool = action["action_type"]
    args = action.get("payload", {})

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
        elif tool == "calendar_create":
            args["idempotency_key"] = idempotency_key
            result = await registry[tool](**args)
        else:
            result = await registry[tool](**args)

        await set_status(client, action_id, "executed")
        confirmation_msg = _action_result_message(tool, args, result)
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
        await asyncio.to_thread(
            lambda: client.table("messages").insert({
                "user_id": user_id,
                "role": "assistant",
                "content": f"⚠️ I couldn't complete that action ({action.get('action_type', 'unknown')}). The error has been logged.",
                "model_used": "system"
            }).execute()
        )

async def _queue_write_tier(client: Client, user_id: str, tool: str, args: dict) -> str:
    """Queue an approve-tier action from inside the loop and describe it.

    The payload must stand alone: once the loop halts, execute_action runs this
    row with no memory of the conversation that produced it, so every argument
    the executor needs has to be resolved by now (design §6).
    """
    await asyncio.to_thread(
        lambda: client.table("action_queue").insert({
            "user_id": user_id,
            "action_type": tool,
            "payload": args,
            "tier": TOOL_TIER_MAP.get(tool, "approve"),
            "status": "awaiting_approval",
            "approved": None,
        }).execute()
    )
    await push_approval(action_type=tool, summary=str(args))
    return f"I've prepared {tool} for your approval. Check the Approvals tab."


async def handle_message(client: Client, message: dict, history: list, user_id: str) -> bool:
    content = message.get("content", "")
    if not content or message.get("role") != "user":
        return False
    print(f"[router] routing: {content[:60]}")

    async def _insert_reply(text: str, model_used: str) -> None:
        row = {
            "user_id": user_id,
            "role": "assistant",
            "content": text,
            "model_used": model_used,
        }
        # Design §8: the UI renders a low-power indicator off this flag, so the
        # user can tell a local answer from a cloud one.
        if model_used == "ollama":
            row["metadata"] = {"low_power": "true"}
        await asyncio.to_thread(
            lambda: client.table("messages").insert(row).execute()
        )

    try:
        # /private and brain-dump decide from the text alone and never enter
        # the loop. Everything else goes to think → act → observe, whose first
        # round doubles as the routing call — so a message needing no tool
        # still costs exactly one model call.
        special = await route_special(client, content, history, GEMINI_API_KEY, user_id)
        if special is None:
            registry = _make_registry([client], [user_id])
            return await run_agent_loop(
                client,
                message=content,
                history=history,
                user_id=user_id,
                message_id=message.get("id"),
                gemini_api_key=GEMINI_API_KEY,
                registry=registry,
                on_write_tier=lambda t, a: _queue_write_tier(client, user_id, t, a),
                insert_reply=_insert_reply,
                degraded_reply=lambda p: degraded_chat(p, content, history),
            )
        result = special
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

    # Only the special paths reach here, and both return plain text — /private
    # answers via Ollama, brain-dump inserts its tasks and reports. Tool calls
    # are the loop's business now.
    if result.get("type") == "text":
        await _insert_reply(result.get("content", ""), result.get("model_used", "system"))
        return True

    return False

async def poll_approved(client: Client):
    while True:
        try:
            await asyncio.sleep(APPROVAL_POLL_INTERVAL_SECONDS)
            rows = await asyncio.to_thread(
                lambda: client.table("action_queue").select("*").eq("status", "approved").execute()
            )
            found = rows.data or []
            print(f"[poll] checking approved queue — {len(found)} rows")
            for row in found:
                await execute_action(client, row)
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

async def reap_stale_message_claims(client: Client):
    """Every 5 min, reset message claims older than 10 min
    with no assistant reply — allows the worker to retry."""
    while True:
        try:
            await asyncio.sleep(300)
            cutoff = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
            stale = await asyncio.to_thread(
                lambda: client.table("messages")
                .select("id, user_id, claimed_at")
                .not_.is_("claimed_by", "null")
                .lt("claimed_at", cutoff)
                .execute()
            )
            reset_count = 0
            for row in (stale.data or []):
                uid = row["user_id"]
                claimed_at = row["claimed_at"]
                reply_check = await asyncio.to_thread(
                    lambda u=uid, ca=claimed_at: client.table("messages")
                    .select("id")
                    .eq("user_id", u)
                    .eq("role", "assistant")
                    .gt("created_at", ca)
                    .limit(1)
                    .execute()
                )
                if not reply_check.data:
                    await asyncio.to_thread(
                        lambda r=row: client.table("messages")
                        .update({"claimed_by": None, "claimed_at": None})
                        .eq("id", r["id"])
                        .execute()
                    )
                    reset_count += 1
            if reset_count > 0:
                print(f"[msg-reaper] Reset {reset_count} stale claim(s)", flush=True)
        except Exception as e:
            print(f"[msg-reaper] error: {e}", flush=True)

async def poll_profile_updates(client: Client):
    """Watch both memory layers for out-of-band edits.

    The user can change either from the phone (Profile, and Profile → Brain)
    without the worker being involved, so the caches the router reads have to
    be refreshed on a timer rather than only on write.
    """
    last_updated_at = None
    last_brain_at = None
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

            brain_res = await asyncio.to_thread(
                lambda: client.table("brain_directives")
                .select("updated_at")
                .order("updated_at", desc=True)
                .limit(1)
                .execute()
            )
            current_brain_at = brain_res.data[0].get("updated_at") if brain_res.data else None
            if last_brain_at is not None and current_brain_at != last_brain_at:
                print("[poll] brain update detected, reloading...")
                await _load_brain(client)
            last_brain_at = current_brain_at
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

async def _load_brain(client: Client) -> None:
    """Load learned directives into the synchronous cache the router reads.

    Scoped to the primary user, matching the single-user assumption already
    baked into fetch_and_cache_profile (which does .limit(1)). When multi-user
    isolation lands, both caches become per-user together.
    """
    try:
        res = await asyncio.to_thread(
            lambda: client.table("user_profile").select("user_id").limit(1).execute()
        )
        if not res.data:
            return
        uid = res.data[0].get("user_id")
        if not uid:
            return
        rows = await fetch_and_cache_directives(client, uid)
        print(f"[brain] loaded {len(rows)} active directive(s)")
    except Exception as e:
        print(f"[brain] load failed: {e}", flush=True)


async def main():
    print("[worker] Project Sunday worker starting...")
    client = get_client()
    await asyncio.to_thread(lambda: fetch_and_cache_profile(client))
    await _load_brain(client)

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

    # Say what to DO about it. The worker no longer opens a browser on its own
    # — scheduled jobs that need Google will fail with ReauthRequired until
    # this is run — so the instruction has to be here, at eye level, once.
    if not all(token_status.values()):
        missing = ", ".join(n for n, ok in token_status.items() if not ok)
        print(f"[worker] ⚠ {missing} will fail until you run:  python3 auth_setup.py")

    # A missing ntfy topic is silent otherwise: notify_ops just skips every
    # push, so reminders and approval alerts vanish with one line buried in
    # the log at the moment they are dropped.
    from config import NTFY_TOPIC
    if NTFY_TOPIC:
        print(f"[worker] ntfy topic: ✓ ({NTFY_TOPIC})")
    else:
        print("[worker] ntfy topic: ✗ NTFY_TOPIC unset — reminders and approval "
              "pushes will be silently dropped. Set it in apps/worker/.env")

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
        if not task.cancelled() and task.exception():
            print(f"[poll] CRITICAL: approval loop died: {task.exception()}", flush=True)
            sys.exit(1)
    poll_task = asyncio.create_task(poll_approved(client))
    poll_task.add_done_callback(_on_poll_done)

    # Start stale processing reaper (Fix 4)
    def _on_reaper_done(task):
        if not task.cancelled() and task.exception():
            print(f"[reaper] CRITICAL: reaper died: {task.exception()}", flush=True)
            sys.exit(1)
    reaper_task = asyncio.create_task(reap_stale_processing(client))
    reaper_task.add_done_callback(_on_reaper_done)

    def _on_msg_reaper_done(task):
        if not task.cancelled() and task.exception():
            print(f"[msg-reaper] CRITICAL: msg reaper died: {task.exception()}",
                  flush=True)
            sys.exit(1)
    msg_reaper_task = asyncio.create_task(reap_stale_message_claims(client))
    msg_reaper_task.add_done_callback(_on_msg_reaper_done)

    # Start scheduler
    sched = Scheduler(client, GEMINI_API_KEY)
    sched.register_handler("morning_briefing", morning_briefing)
    sched.register_handler("email_scan", email_scan)
    sched.register_handler("meal_checkin", meal_checkin)
    # meal_checkin upserts this row when it finds no free window, and
    # deletes it again on success. Without a handler the scheduler just
    # logged "no handler for job" and the retry never once ran.
    sched.register_handler("meal_checkin_retry", meal_checkin)
    sched.register_handler("nightly_maintenance", nightly_maintenance)
    sched.register_handler("calendar_prep", calendar_prep)
    sched.register_handler("task_tracker", task_tracker)
    sched.register_handler("cold_storage_archive", cold_storage_archive)
    sched.register_handler("daily_brief", send_daily_brief_job)
    sched.register_handler("sync_calendar", sync_calendar_job)
    scheduler_task = asyncio.create_task(sched.run())

    def _on_scheduler_done(task):
        if not task.cancelled() and task.exception():
            print(f"[scheduler] CRITICAL: scheduler died: {task.exception()}", 
                  flush=True)
            sys.exit(1)
    scheduler_task.add_done_callback(_on_scheduler_done)

    # Start reminders poll loop
    def _on_reminders_done(task):
        if not task.cancelled() and task.exception():
            print(f"[poll_reminders] CRITICAL: reminders loop died: {task.exception()}", flush=True)
            sys.exit(1)
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
            }, on_conflict="job_name").execute()
        )
    except Exception as e:
        print(f"[worker] Failed to register sync_calendar job: {e}")

    # Run calendar sync on startup — via run_now, not by calling the handler
    # directly. A direct call is invisible to the scheduler's in-flight guard,
    # so this raced catch-up and ran sync_calendar twice on every start.
    sync_cal_task = asyncio.create_task(sched.run_now("sync_calendar"))

    def _on_sync_calendar_done(task):
        if not task.cancelled() and task.exception():
            print(f"[sync_calendar] CRITICAL: sync_calendar died: {task.exception()}", 
                  flush=True)
            sys.exit(1)
    sync_cal_task.add_done_callback(_on_sync_calendar_done)

    # On startup: send today's brief if not already sent
    import datetime as dt
    try:
        today = dt.date.today().isoformat()
        # Phase 3 collapsed the get_active_users fan-out and missed this site,
        # which queried user_profile directly. Its loop variable was `row`,
        # which is also the name of the utils helper — a shadow waiting for
        # whoever imported it here next.
        user_id = (await resolve_user(client))["user_id"]
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
    startup_watermark = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

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
                            .update({"claimed_by": "mac",
                                     "claimed_at": datetime.now(timezone.utc).isoformat()})
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
                    profiles = client.table("user_profile").select("user_id").execute()
                    for row in (profiles.data or []):
                        uid = row.get("user_id")
                        if uid:
                            client.table("messages").insert({
                                "user_id": uid,
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
