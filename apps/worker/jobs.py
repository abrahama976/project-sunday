"""Scheduled job handler functions.

Each handler has the signature:
    async def handler(client: Client, gemini_api_key: str) -> None

These are registered with the Scheduler in main.py.
"""
import asyncio
from datetime import date, datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from supabase import Client
from utils import as_datetime, display_name, resolve_user, row
import json
import gzip
import io

from google import genai
from google.genai import types
from config import GEMINI_MODEL, GEMINI_MAX_TOKENS
from budget_gate import pick_model, check_and_increment
from executors.weather_ops import get_today_weather
from executors.notify_ops import push_brief_ready, push_approval
from utils import generate_with_retry


async def morning_briefing(client: Client, gemini_api_key: str) -> None:
    """Generate the daily morning briefing."""
    today = date.today()
    today_str = today.isoformat()

    user = await resolve_user(client)
    uid, name = user["user_id"], user["name"]

    existing = await asyncio.to_thread(
        lambda: client.table("daily_briefings")
        .select("id")
        .eq("user_id", uid)
        .eq("briefing_date", today_str)
        .maybe_single()
        .execute()
    )

    if row(existing):
        print(f"[briefing] already generated for {name} on {today_str}")
        return

    sections: dict = {}

    # 1. Calendar events
    try:
        from executors.calendar_ops import calendar_query
        events = await calendar_query(query="", days_ahead=1)
        sections["schedule"] = events
    except Exception as e:
        sections["schedule"] = f"(Calendar unavailable: {e})"

    # 2. Due tasks
    try:
        from executors.task_ops import task_list
        tasks = await task_list(client, status="open", due_before=today_str)
        sections["tasks"] = tasks
    except Exception as e:
        sections["tasks"] = f"(Tasks unavailable: {e})"

    # 3. Priority emails
    try:
        from executors.gmail_ops import gmail_priority_scan
        emails = await gmail_priority_scan(max_results=5)
        sections["emails"] = emails
    except Exception as e:
        sections["emails"] = f"(Email scan unavailable: {e})"

    # News sections used to sit here — an RSS pull from `news_items` and four
    # `web_search` calls for regional headlines. Retired in Phase 3 along with
    # the news_fetch job that filled the table.

    prompt = f"""You are Project Sunday, generating a morning briefing for {name}.
Today is {today.strftime('%A, %d %B %Y')}.

Compose a concise, useful daily briefing in markdown format.
Include these sections (skip any that have no data):

## Schedule
{sections.get('schedule', '(No data)')}

## Tasks Due
{sections.get('tasks', '(No data)')}

## Priority Emails
{sections.get('emails', '(No data)')}

Rules:
- Keep it brief and actionable.
- Use bullet points, not paragraphs.
- Start with a one-line summary of the day.
- If a section has "(No data)" or "(unavailable)", skip it entirely.
- Don't include the section headers if there's nothing to show."""

    try:
        ai_client = genai.Client(api_key=gemini_api_key)
        model_id = await pick_model(client, uid, allow_flash=False)
        if model_id == "EXHAUSTED" or model_id == "ollama":
            content = "⚠️ Briefing generation skipped: LLM budget exhausted."
        else:
            await check_and_increment(client, uid, model_id)
            response = await generate_with_retry(
                lambda: ai_client.models.generate_content(
                    model=model_id,
                    contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
                    config=types.GenerateContentConfig(
                        max_output_tokens=GEMINI_MAX_TOKENS,
                        temperature=0.4,
                    ),
                )
            )
            content = "".join(
                p.text for p in response.candidates[0].content.parts
                if hasattr(p, "text") and p.text
            ).strip()
    except Exception as e:
        content = f"⚠️ Briefing generation failed: {e}"

    await asyncio.to_thread(
        lambda: client.table("daily_briefings").insert({
            "user_id": uid,
            "briefing_date": today_str,
            "content": content,
            "sections": json.dumps(sections),
        }).execute()
    )

    await asyncio.to_thread(
        lambda: client.table("messages").insert({
            "user_id": uid,
            "role": "assistant",
            "content": f"☀️ **Morning Briefing — {today.strftime('%A, %d %B')}**\n\n{content}",
            "model_used": "gemini",
        }).execute()
    )
    print(f"[briefing] generated for {name} on {today_str}")


async def email_scan(client: Client, gemini_api_key: str) -> None:
    try:
        from executors.gmail_ops import gmail_priority_scan
        result = await gmail_priority_scan(max_results=5)
        try:
            emails = json.loads(result)
            count = len(emails)
        except (json.JSONDecodeError, TypeError):
            count = 0 if "No unread" in result else 1
        print(f"[email_scan] found {count} priority email(s)")
    except Exception as e:
        print(f"[email_scan] error: {e}")


async def meal_checkin(client: Client, gemini_api_key: str) -> None:
    user = await resolve_user(client)
    uid, name = user["user_id"], user["name"]

    loc_result = await asyncio.to_thread(
        lambda: client.table("user_location").select("timezone").eq("user_id", uid).limit(1).maybe_single().execute()
    )
    tz_str = row(loc_result).get("timezone") or "Australia/Sydney"
    now = datetime.now(ZoneInfo(tz_str))

    try:
        from executors.calendar_ops import calendar_query
        events_str = await calendar_query(query="", days_ahead=1)

        prompt = f"""You are checking {name}'s schedule to see if they have a free 15-minute gap in the next 2 hours to eat.
Current time: {now.strftime('%Y-%m-%d %H:%M')}

Schedule:
{events_str}

Is there a free 15-minute window in the next 2 hours? Reply YES or NO only."""

        model_id = await pick_model(client, uid, allow_flash=False)
        if model_id == "EXHAUSTED" or model_id == "ollama":
            print(f"[meal_checkin] LLM budget exhausted for {name} — skipping")
            return
        await check_and_increment(client, uid, model_id)

        ai_client = genai.Client(api_key=gemini_api_key)
        response = await generate_with_retry(
            lambda: ai_client.models.generate_content(
                model=model_id,
                contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
                config=types.GenerateContentConfig(max_output_tokens=10, temperature=0.1),
            )
        )
        ans = response.candidates[0].content.parts[0].text.strip().upper()
        if "YES" in ans:
            msg = "Hey, it looks like you have a moment — did you eat? Let me log it for you."
            await asyncio.to_thread(
                lambda: client.table("messages").insert({
                    "user_id": uid,
                    "role": "assistant",
                    "content": msg,
                    "model_used": "system",
                }).execute()
            )
            print(f"[meal_checkin] sent proactive check-in for {name}")

            # Delete any existing retry
            await asyncio.to_thread(
                lambda: client.table("scheduled_jobs").delete().eq("job_name", "meal_checkin_retry").execute()
            )
        else:
            print(f"[meal_checkin] no free window for {name}, silently skipping and scheduling retry")
            retry_hour = (datetime.now(timezone.utc).hour + 1) % 24
            await asyncio.to_thread(
                lambda: client.table("scheduled_jobs").upsert({
                    "job_name": "meal_checkin_retry",
                    "cron_expr": f"0 {retry_hour} * * *",
                    "timezone": "UTC",
                    "config": {"description": "Retry meal check-in"}
                }).execute()
            )
    except Exception as e:
        print(f"[meal_checkin] failed for {name}: {e}")


async def nightly_maintenance(client: Client, gemini_api_key: str) -> None:
    print("[nightly_maintenance] starting")
    now_utc = datetime.now(timezone.utc)
    
    user = await resolve_user(client)
    uid = user["user_id"]

    # 1. Archive tasks > 7 days old
    try:
        cutoff_7 = (now_utc - timedelta(days=7)).isoformat()
        await asyncio.to_thread(
            lambda: client.table("tasks")
            .update({"is_archived": True})
            .eq("user_id", uid)
            .eq("status", "done")
            .lt("completed_at", cutoff_7)
            .execute()
        )
    except Exception as e:
        print(f"[nightly_maintenance] tasks error: {e}")

    # 2. Soft-delete health_logs > 30 days old
    try:
        cutoff_30 = (now_utc - timedelta(days=30)).date().isoformat()
        await asyncio.to_thread(
            lambda: client.table("health_logs")
            .update({"is_archived": True})
            .eq("user_id", uid)
            .lt("log_date", cutoff_30)
            .execute()
        )
    except Exception as e:
        print(f"[nightly_maintenance] health_logs error: {e}")

    # 3. Compress messages > 14 days old
    try:
        cutoff_14 = (now_utc - timedelta(days=14)).isoformat()
        res = await asyncio.to_thread(
            lambda: client.table("messages")
            .select("*")
            .eq("user_id", uid)
            .eq("is_deleted", False)
            .lt("created_at", cutoff_14)
            .order("created_at", desc=False)
            .execute()
        )
        msgs = res.data or []
        if msgs:
            text_lines = []
            for m in msgs:
                role = "User" if m["role"] == "user" else "Assistant"
                text_lines.append(f"{role} ({m['created_at']}): {m['content']}")
            prompt = "Summarise the following conversation into a single, concise paragraph capturing the key topics, tasks, and context discussed.\n\n" + "\n".join(text_lines)
            
            # Budget gate for nightly summarisation
            model_id = await pick_model(client, uid, allow_flash=False)
            if model_id == "EXHAUSTED" or model_id == "ollama":
                print("[nightly_maintenance] LLM budget exhausted — skipping summarisation")
            else:
                await check_and_increment(client, uid, model_id)
                ai_client = genai.Client(api_key=gemini_api_key)
                response = await generate_with_retry(
                    lambda: ai_client.models.generate_content(
                        model=model_id,
                        contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
                        config=types.GenerateContentConfig(max_output_tokens=1000)
                    )
                )
                summary = (
                    "".join(
                        p.text for p in response.candidates[0].content.parts
                        if hasattr(p, "text") and p.text
                    ).strip()
                    if response and response.candidates and response.candidates[0].content
                    else ""
                )
            
                await asyncio.to_thread(
                    lambda: client.table("message_summaries").insert({
                        "user_id": uid,
                        "summary": summary,
                        "message_count": len(msgs),
                        "date_from": msgs[0]["created_at"],
                        "date_to": msgs[-1]["created_at"]
                    }).execute()
                )
            
            for m in msgs:
                await asyncio.to_thread(
                    lambda: client.table("messages").update({"is_deleted": True}).eq("id", m["id"]).execute()
                )
            print(f"[nightly_maintenance] compressed {len(msgs)} messages for {uid}")
    except Exception as e:
        print(f"[nightly_maintenance] messages error: {e}")


async def calendar_prep(client: Client, gemini_api_key: str) -> None:
    print("[calendar_prep] starting")
    try:
        from executors.calendar_ops import calendar_query
        events_str = await calendar_query(query="", days_ahead=1)
        if "No events found" in events_str:
            print("[calendar_prep] No events to prep for today.")
            return

        user = await resolve_user(client)
        uid = user["user_id"]

        loc_result = await asyncio.to_thread(
            lambda: client.table("user_location").select("lat, lng").eq("user_id", uid).limit(1).maybe_single().execute()
        )
        loc_data = row(loc_result)
        origin_lat = loc_data.get("lat")
        origin_lng = loc_data.get("lng")

        model_id = await pick_model(client, uid, allow_flash=False)
        if model_id == "EXHAUSTED" or model_id == "ollama":
            print("[calendar_prep] LLM budget exhausted — skipping")
            return
        await check_and_increment(client, uid, model_id)

        ai_client = genai.Client(api_key=gemini_api_key)
        
        prompt_extract = f"""Extract a JSON array of events from this calendar string.
Each object must have 'title', 'location', and 'needs_prep' (boolean, true if there are attendees or it's a meeting).
Calendar string:
{events_str}
Return ONLY valid JSON (no markdown block)."""
        
        response_ext = await generate_with_retry(
            lambda: ai_client.models.generate_content(
                model=model_id,
                contents=[types.Content(role="user", parts=[types.Part(text=prompt_extract)])],
                config=types.GenerateContentConfig(max_output_tokens=500, temperature=0.1),
            )
        )
        json_str = response_ext.candidates[0].content.parts[0].text.strip().removeprefix("```json").removesuffix("```").strip()
        try:
            events = json.loads(json_str)
        except json.JSONDecodeError:
            events = []
            print("[calendar_prep] Failed to decode JSON from AI response")

        for ev in events:
            if ev.get("needs_prep"):
                title = f"Prep for {ev['title']}"
                await asyncio.to_thread(
                    lambda: client.table("tasks").insert({
                        "user_id": uid,
                        "title": title,
                        "category": "work",
                        "tags": ["prep"],
                        "flexibility_score": 2,
                        "source": "calendar_prep"
                    }).execute()
                )
                print(f"[calendar_prep] created task: {title}")
                
                # Check for travel
                dest = ev.get("location")
                if dest and origin_lat and origin_lng:
                    # trip_plan, not travel_directions: this asked Google for transit
                    # directions, which needs Maps billing — so every travel task this
                    # job tried to create has been failing silently. TfNSW does transit
                    # better, live, and for free.
                    from executors.travel_ops import trip_plan
                    origin_str = f"{origin_lat},{origin_lng}"
                    travel_result = await trip_plan(destination=dest, origin=origin_str)
                    
                    if not travel_result.startswith(("Error", "No public transport", "No journeys")):
                        await asyncio.to_thread(
                            lambda: client.table("tasks").insert({
                                "user_id": uid,
                                "title": f"Travel to {ev['title']}",
                                "description": travel_result[:500],
                                "category": "personal",
                                "tags": ["travel"],
                                "flexibility_score": 1,
                                "source": "calendar_prep"
                            }).execute()
                        )
                        print(f"[calendar_prep] added travel task to {dest}")
                        
    except Exception as e:
        print(f"[calendar_prep] failed: {e}")

async def task_tracker(client: Client, gemini_api_key: str) -> None:
    print("[task_tracker] starting")
    now_utc = datetime.now(timezone.utc)

    # ── Fix 5: Quiet hours check FIRST — before any DB queries or LLM calls ──
    # Fetch all distinct user timezones and check each user individually below.
    # For the global gate, we check if ALL known users are in quiet hours.
    # If no users have a timezone set, default to Australia/Sydney.
    loc_res = await asyncio.to_thread(
        lambda: client.table("user_location")
        .select("user_id, timezone")
        .execute()
    )
    user_tz_map: dict[str, str] = {}
    if loc_res.data:
        # Named `loc`, not `row` — `row` is the maybe_single helper imported at
        # the top of this module, and shadowing it here would turn any later
        # row(...) call in this function into "'dict' object is not callable".
        for loc in loc_res.data:
            uid = loc.get("user_id")
            tz = loc.get("timezone")
            if uid and tz:
                user_tz_map[uid] = tz

    res = await asyncio.to_thread(
        lambda: client.table("tasks")
        .select("id, title, user_id, last_nudged_at")
        .eq("status", "open")
        .execute()
    )

    tasks = res.data or []
    tasks_to_nudge = []
    for t in tasks:
        nudged_at = t.get("last_nudged_at")
        if not nudged_at:
            tasks_to_nudge.append(t)
            continue
        try:
            nudged_dt = datetime.fromisoformat(nudged_at.replace("Z", "+00:00"))
            if nudged_dt < (now_utc - timedelta(hours=2)):
                tasks_to_nudge.append(t)
        except ValueError:
            tasks_to_nudge.append(t)

    from collections import defaultdict
    user_tasks = defaultdict(list)
    for t in tasks_to_nudge:
        user_tasks[t.get("user_id")].append(t)

    for uid, utasks in user_tasks.items():
        if not uid:
            continue

        # ── Fix 5: Per-user quiet hours check ──
        tz_str = user_tz_map.get(uid, "Australia/Sydney")
        try:
            local_now = datetime.now(ZoneInfo(tz_str))
        except Exception:
            local_now = datetime.now(ZoneInfo("Australia/Sydney"))

        local_hour = local_now.hour
        if local_hour >= 23 or local_hour < 8:
            print(f"[task_tracker] quiet hours for user {uid} (local {local_now.strftime('%H:%M')}) — skipping")
            continue

        # ── Fix 2: Daily per-user nudge cap (max 3) ──
        today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        nudge_count_res = await asyncio.to_thread(
            lambda: client.table("messages")
            .select("*", count="exact", head=True)
            .eq("user_id", uid)
            .eq("role", "assistant")
            .eq("model_used", "task_tracker")
            .gte("created_at", today_start.isoformat())
            .execute()
        )
        daily_nudge_count = nudge_count_res.count or 0
        if daily_nudge_count >= 3:
            print(f"[task_tracker] daily nudge cap reached for user {uid} ({daily_nudge_count}/3) — skipping")
            continue

        sample = utasks[:2]
        task_titles = [t["title"] for t in sample]

        prompt = f"""You are Project Sunday. The user has these open tasks they haven't been nudged about in a while:
{json.dumps(task_titles)}

Write a very short, casual 1-sentence nudge for the chat interface. Be friendly. No robotic language."""

        try:
            # Budget gate for task_tracker (per-user)
            model_id = await pick_model(client, uid, allow_flash=False)
            if model_id == "EXHAUSTED" or model_id == "ollama":
                print(f"[task_tracker] LLM budget exhausted for user {uid} — skipping")
                continue
            await check_and_increment(client, uid, model_id)

            ai_client = genai.Client(api_key=gemini_api_key)
            response = await generate_with_retry(
                lambda: ai_client.models.generate_content(
                    model=model_id,
                    contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
                    config=types.GenerateContentConfig(max_output_tokens=100, temperature=0.7)
                )
            )
            msg_content = "".join(p.text for p in response.candidates[0].content.parts if hasattr(p, "text") and p.text).strip()

            await asyncio.to_thread(
                lambda: client.table("messages").insert({
                    "user_id": uid,
                    "role": "assistant",
                    "content": "👋 " + msg_content,
                    "model_used": "task_tracker"
                }).execute()
            )

            for t in sample:
                await asyncio.to_thread(
                    lambda: client.table("tasks").update({"last_nudged_at": now_utc.isoformat()}).eq("id", t["id"]).execute()
                )
            print(f"[task_tracker] Nudged user {uid} about {len(sample)} tasks")
        except Exception as e:
            print(f"[task_tracker] failed for user {uid}: {e}")

async def cold_storage_archive(client: Client, gemini_api_key: str) -> None:
    print("[cold_storage_archive] starting")
    now_utc = datetime.now(timezone.utc)
    cutoff_30 = (now_utc - timedelta(days=30)).isoformat()

    try:
        # 1. Fetch candidates
        msg_res = await asyncio.to_thread(
            lambda: client.table("messages")
            .select("*")
            .eq("is_deleted", True)
            .lt("created_at", cutoff_30)
            .execute()
        )
        msgs = msg_res.data or []

        task_res = await asyncio.to_thread(
            lambda: client.table("tasks")
            .select("*")
            .eq("is_archived", True)
            .lt("completed_at", cutoff_30)
            .execute()
        )
        tasks = task_res.data or []

        if not msgs and not tasks:
            print("[cold_storage_archive] Nothing to archive.")
            return

        # Snapshot exact IDs before any mutation
        msg_ids = [m["id"] for m in msgs]
        task_ids = [t["id"] for t in tasks]
        expected_msg_count = len(msgs)
        expected_task_count = len(tasks)

        archive_data = {
            "archived_at": now_utc.isoformat(),
            "messages": msgs,
            "tasks": tasks
        }

        json_bytes = json.dumps(archive_data).encode('utf-8')
        compressed = gzip.compress(json_bytes)

        filename = f"archive_{now_utc.strftime('%Y%m%d_%H%M%S')}.json.gz"

        # 2. Upload to cold_archive
        await asyncio.to_thread(
            lambda: client.storage.from_("cold_archive").upload(
                path=filename,
                file=compressed,
                file_options={"content-type": "application/gzip"}
            )
        )
        print(f"[cold_storage_archive] Uploaded {filename} to Storage")

        # 3. VERIFY — download the file back and validate integrity
        try:
            downloaded_bytes = await asyncio.to_thread(
                lambda: client.storage.from_("cold_archive").download(filename)
            )

            decompressed = gzip.decompress(downloaded_bytes)
            verified_data = json.loads(decompressed)

            verified_msg_count = len(verified_data.get("messages", []))
            verified_task_count = len(verified_data.get("tasks", []))

            if verified_msg_count != expected_msg_count:
                print(f"[cold_storage_archive] ABORT — message count mismatch: uploaded {expected_msg_count}, verified {verified_msg_count}")
                return
            if verified_task_count != expected_task_count:
                print(f"[cold_storage_archive] ABORT — task count mismatch: uploaded {expected_task_count}, verified {verified_task_count}")
                return

            print(f"[cold_storage_archive] Verification passed: {verified_msg_count} messages, {verified_task_count} tasks")

        except Exception as verify_err:
            print(f"[cold_storage_archive] ABORT — verification failed: {verify_err}")
            return

        # 4. Hard delete ONLY using the exact IDs captured before upload
        if msg_ids:
            for i in range(0, len(msg_ids), 100):
                chunk = msg_ids[i:i+100]
                await asyncio.to_thread(
                    lambda: client.table("messages").delete().in_("id", chunk).execute()
                )
        if task_ids:
            for i in range(0, len(task_ids), 100):
                chunk = task_ids[i:i+100]
                await asyncio.to_thread(
                    lambda: client.table("tasks").delete().in_("id", chunk).execute()
                )

        print(f"[cold_storage_archive] Hard deleted {len(msg_ids)} messages and {len(task_ids)} tasks")
    except Exception as e:
        print(f"[cold_storage_archive] error: {e}")

def _as_markdown(lines: list[str]) -> str:
    """Join brief lines so a markdown renderer sees the blocks we meant.

    `"\\n".join(...)` looks right in a terminal and is wrong in markdown: a
    single newline is a soft break, so consecutive lines collapse into one
    paragraph. That is why the brief arrived reading
    "**Friday, 12 June 2026** Today's weather (Sydney): Drizzle…" — two lines
    written, one line rendered.

    Blocks are separated by a blank line; runs of bullets stay on single
    newlines so the list renders tight rather than spaced out.
    """
    blocks: list[str] = []
    bullets: list[str] = []

    for line in lines:
        if line.startswith("- "):
            bullets.append(line)
            continue
        if bullets:
            blocks.append("\n".join(bullets))
            bullets = []
        blocks.append(line)

    if bullets:
        blocks.append("\n".join(bullets))
    return "\n\n".join(blocks)


async def send_daily_brief(client: Client, user_id: str) -> None:
    import datetime
    import json
    import asyncio
    import re
    from zoneinfo import ZoneInfo
    
    # User Profile
    # `content` as well as `name`: the column is NULL and the name is in the
    # markdown. See utils.display_name — this line printed "Good morning, None".
    profile_res = await asyncio.to_thread(lambda: client.table("user_profile").select("name, content").eq("user_id", user_id).limit(1).maybe_single().execute())
    name = display_name(row(profile_res))
    
    loc_result = await asyncio.to_thread(lambda: client.table("user_location").select("timezone").eq("user_id", user_id).limit(1).maybe_single().execute())
    tz_str = row(loc_result).get("timezone") or "Australia/Sydney"
    
    tz = ZoneInfo(tz_str)
    today = datetime.datetime.now(tz)
    formatted_date = today.strftime("%A, %-d %B %Y")
    
    out = []
    out.append(f"## Good morning, {name} ☀️")
    out.append(f"**{formatted_date}**")
    
    weather = await get_today_weather()
    weather_line = weather.get("summary_line", "") if weather else ""
    if weather_line:
        out.append(f"Today's weather (Sydney): {weather_line}")
    
    # Schedule
    out.append("### 📅 Today's Schedule")
    startOfDay = today.replace(hour=0, minute=0, second=0, microsecond=0)
    endOfDay = today.replace(hour=23, minute=59, second=59, microsecond=999)
    events_res = await asyncio.to_thread(lambda: client.table("calendar_events").select("*").eq("user_id", user_id).gte("start_time", startOfDay.isoformat()).lte("start_time", endOfDay.isoformat()).order("start_time").execute())
    events = (events_res.data if events_res else None) or []
    if not events:
        out.append("- *Nothing to report*")
    else:
        for ev in events:
            # check if all day
            st = datetime.datetime.fromisoformat(ev["start_time"].replace("Z", "+00:00")).astimezone(tz)
            en = datetime.datetime.fromisoformat(ev["end_time"].replace("Z", "+00:00")).astimezone(tz)
            if st.hour == 0 and st.minute == 0 and en.hour == 0 and en.minute == 0:
                time_str = "All day"
            else:
                time_str = st.strftime("%-I:%M %p")
            line = f"- **{time_str}** — {ev['title']}"
            if ev.get("location"):
                loc = ev['location']
                if len(loc) > 40:
                    loc = loc[:37] + "..."
                line += f" *({loc})*"
            out.append(line)

            # A leave-by time is the useful half of "you have a thing at 6:30".
            # Best-effort: the brief is worth more on time without it than late
            # with it, so any failure here is a missing line, never a missing
            # brief. Costs no model call — TfNSW and arithmetic only.
            if ev.get("location") and time_str != "All day":
                try:
                    from executors.travel_ops import plan_journeys, leave_time_from
                    from config import TRAVEL_BUFFER_MINUTES
                    planned = await plan_journeys(
                        destination=ev["location"], arrive_by=ev["start_time"],
                        client=client, user_id=user_id,
                    )
                    if planned.get("ok"):
                        depart = leave_time_from(planned["journeys"], TRAVEL_BUFFER_MINUTES)
                        if depart:
                            best = planned["journeys"][0]
                            out.append(
                                f"  ↳ leave by **{depart.astimezone(tz).strftime('%-I:%M %p')}**"
                                f" ({best['duration_min']} min, {best['changes']} change"
                                f"{'s' if best['changes'] != 1 else ''})"
                            )
                except Exception as e:
                    print(f"[brief] leave-by unavailable for {ev.get('title')}: {e}")

    # Tasks
    out.append("### ✅ Tasks Due Today")
    tasks_res = await asyncio.to_thread(lambda: client.table("tasks").select("*").eq("user_id", user_id).eq("status", "open").eq("is_archived", False).lte("due_date", startOfDay.date().isoformat()).execute())
    tasks = (tasks_res.data if tasks_res else None) or []
    if not tasks:
        out.append("- Clear — enjoy the day.")
    else:
        for t in tasks:
            out.append(f"- {t['title']}")

    # Emails
    out.append("### 📬 Inbox Highlights")
    BRIEF_EMAIL_SKIP_SENDERS = [
        "notifications@github.com",
        "noreply@github.com",
        "noreply@vercel.com",
        "no-reply@",
        "donotreply@",
        "mailer-daemon@",
    ]
    try:
        from executors.gmail_ops import gmail_priority_scan
        email_res = await gmail_priority_scan(max_results=10)
        emails = json.loads(email_res)
        valid_emails = []
        for e in emails:
            sender = e.get("from", "")
            if not any(skip in sender.lower() for skip in BRIEF_EMAIL_SKIP_SENDERS):
                valid_emails.append(e)
        if not valid_emails:
            out.append("- *Nothing to report*")
        else:
            for e in valid_emails[:5]:
                sender = e.get("from", "Unknown")
                # Extract display name
                if "<" in sender:
                    sender = sender.split("<")[0].strip().strip('"')
                out.append(f"- **{sender}**: {e.get('subject', '(No subject)')}")
    except Exception as e:
        out.append("- *Nothing to report*")

    full_text = _as_markdown(out)
    if len(full_text) > 900:
        full_text = full_text[:897] + "..."

    try:
        await asyncio.to_thread(
            lambda: client.table("messages").insert({
                "user_id": user_id,
                "role": "assistant",
                "content": full_text,
                "model_used": "system",
            }).execute()
        )
        await push_brief_ready()
        print(f"[jobs] Daily brief sent for {user_id[:8]}")
    except Exception as e:
        print(f"[jobs] Failed to save daily brief for {user_id[:8]}: {e}")

async def send_daily_brief_job(client: Client, gemini_api_key: str) -> None:
    """Scheduler entry point for the daily brief.

    Was `send_daily_brief_for_all_users`, looping every `user_profile` row —
    and shadowing the `row()` helper with its loop variable while it did.
    """
    user = await resolve_user(client)
    await send_daily_brief(client, user["user_id"])



async def sync_calendar_job(client: Client, gemini_api_key: str) -> None:
    print("[sync_calendar] starting")
    try:
        from executors.calendar_ops import sync_calendar_events
        result = await sync_calendar_events(client)
        print(f"[sync_calendar] {result}")
    except Exception as e:
        print(f"[sync_calendar] failed: {e}")



# How long before you need to walk out the door the push should land. Enough
# to finish what you are doing; not so much that you forget it happened.
TRAVEL_ALERT_LEAD_MINUTES = 10

# Inside this many minutes of a planned leave time, re-plan on every tick: this
# is the window where a delay still has time to move the alert and change what
# you do. Outside it, re-planning is mostly redundant.
TRAVEL_REPLAN_LEAD_MINUTES = 20
# ...and outside that window, no more often than this. An event five hours out
# used to cost a full search every five minutes — around sixty of them before
# the alert was ever due. Nothing was learned from the fifty-nine that changed
# nothing.
TRAVEL_REPLAN_MIN_INTERVAL_MINUTES = 30


def travel_replan_due(planned_at, planned_leave_at, now,
                      lead_minutes=TRAVEL_REPLAN_LEAD_MINUTES,
                      min_interval_minutes=TRAVEL_REPLAN_MIN_INTERVAL_MINUTES) -> bool:
    """Should this event be planned again on this tick?

    Pure, and separated from the job because it decides how much of the day's
    TfNSW traffic exists. Three cases:

    - Never planned → yes, obviously.
    - Close to the planned leave time → yes, every tick. This is exactly when a
      late train needs to move the alert, so cheapness stops mattering.
    - Otherwise → only if the last plan has gone stale.
    """
    if planned_at is None or planned_leave_at is None:
        return True
    if (planned_leave_at - now) <= timedelta(minutes=lead_minutes):
        return True
    return (now - planned_at) >= timedelta(minutes=min_interval_minutes)


async def travel_watch(client: Client, gemini_api_key: str) -> None:
    """Push a leave-now alert before calendar events that have a location.

    Recomputes as the leave time approaches on purpose: a train running late
    should move the alert rather than leave a stale one standing. What it no
    longer does is recompute an event that is still hours away on every single
    tick — `travel_replan_due` decides that, and `travel_alerts` remembers both
    what was planned and what was actually sent.

    Runs the cheap search (`depth="baseline"`) by default and escalates to the
    full multi-strategy one only when the baseline looks poor. A job on a
    five-minute timer is the wrong place to spend four searches per event; a
    bad-looking baseline is the right place to spend them.

    Makes NO model call. Everything here is a TfNSW lookup and arithmetic, so
    it costs nothing against the 250/day budget however often it runs.
    """
    from executors.travel_ops import plan_journeys, leave_time_from
    from executors.notify_ops import push
    from config import TRAVEL_BUFFER_MINUTES

    try:
        user = await resolve_user(client)
    except Exception as e:
        print(f"[travel_watch] no user to watch for: {e}")
        return

    uid = user["user_id"]
    tz_res = await asyncio.to_thread(
        lambda: client.table("user_location").select("timezone")
        .eq("user_id", uid).limit(1).maybe_single().execute()
    )
    tz = ZoneInfo(row(tz_res).get("timezone") or "Australia/Sydney")
    now = datetime.now(tz)

    events_res = await asyncio.to_thread(
        lambda: client.table("calendar_events")
        .select("event_id, title, start_time, location")
        .eq("user_id", uid)
        .gte("start_time", now.isoformat())
        .lte("start_time", (now + timedelta(hours=6)).isoformat())
        .order("start_time")
        .execute()
    )

    for event in (getattr(events_res, "data", None) or []):
        location = (event.get("location") or "").strip()
        event_id = event.get("event_id")
        if not location or not event_id:
            continue

        # One indexed lookup carries both answers: whether they have already
        # been told, and when this event was last planned.
        record = row(await asyncio.to_thread(
            lambda e=event_id: client.table("travel_alerts")
            .select("id, alerted_at, planned_at, planned_leave_at")
            .eq("user_id", uid).eq("event_id", e).limit(1).maybe_single().execute()
        ))

        # Already told them about this one. Nothing more to do, ever.
        if record.get("alerted_at"):
            continue

        planned_at = as_datetime(record.get("planned_at"))
        planned_leave = as_datetime(record.get("planned_leave_at"))
        if not travel_replan_due(planned_at, planned_leave, now):
            continue

        try:
            result = await plan_journeys(
                destination=location, arrive_by=event["start_time"],
                client=client, user_id=uid, depth="baseline",
            )
            # A long wait or a lot of changes is exactly the case the biased
            # searches exist for, so it is worth paying for them here.
            if result.get("ok"):
                best = result["journeys"][0]
                if best["wait_min"] >= 10 or best["changes"] >= 2:
                    deeper = await plan_journeys(
                        destination=location, arrive_by=event["start_time"],
                        client=client, user_id=uid, depth="full",
                    )
                    if deeper.get("ok"):
                        result = deeper
        except Exception as e:
            print(f"[travel_watch] planning failed for {event.get('title')}: {e}")
            continue

        if not result.get("ok"):
            print(f"[travel_watch] {event.get('title')}: {result.get('error')}")
            continue

        best = result["journeys"][0]
        leave_at = leave_time_from(result["journeys"], TRAVEL_BUFFER_MINUTES)
        if leave_at is None:
            continue

        # Remember what was decided, whether or not it is time to say it. This
        # is what stops the next tick redoing the same search.
        await asyncio.to_thread(
            lambda e=event_id, la=leave_at, st=event["start_time"]:
            client.table("travel_alerts").upsert({
                "user_id": uid, "event_id": e,
                "event_start": st,
                "leave_at": la.isoformat(),
                "planned_leave_at": la.isoformat(),
                "planned_at": now.isoformat(),
            }, on_conflict="user_id,event_id").execute()
        )

        # Only inside the lead window. Earlier is noise; once it is past, the
        # alert has missed its moment and saying so late is worse than silence.
        minutes_until = (leave_at - now).total_seconds() / 60
        if not (0 <= minutes_until <= TRAVEL_ALERT_LEAD_MINUTES):
            continue

        local_leave = leave_at.astimezone(tz).strftime("%-I:%M %p")
        local_arrive = best["arrive"].astimezone(tz).strftime("%-I:%M %p")
        body = (
            f"Leave by {local_leave} for {event.get('title') or 'your next event'}"
            f" — {best['duration_min']} min, {best['changes']} change"
            f"{'s' if best['changes'] != 1 else ''}, arriving {local_arrive}."
        )
        if best.get("drive_min"):
            body += f" Drive {best['drive_min']} min to the station first."
        if not best["realtime"]:
            body += " (timetable only — no live data for this trip)"

        sent = await push("🚆 Time to go", body, priority="high", tags=["train"])

        # `alerted_at` is set only after a successful push, so a failed
        # notification is retried on the next tick rather than silently marked
        # as delivered. The planning columns above are already saved either way.
        if sent:
            await asyncio.to_thread(
                lambda e=event_id: client.table("travel_alerts")
                .update({"alerted_at": datetime.now(timezone.utc).isoformat()})
                .eq("user_id", uid).eq("event_id", e).execute()
            )
            print(f"[travel_watch] alerted: {body}")


# ── The local network ──────────────────────────────────────────────────────
# Discovering which services exist near home, so trip planning can consider
# all of them rather than whichever corridor TfNSW happens to prefer.

async def refresh_nearby_services(client: Client, gemini_api_key: str) -> None:
    """Rediscover the stops, routes and frequencies near the default place.

    Weekly, because the transit near a fixed address changes on the scale of
    months. Makes NO model call — stop_finder and departure_mon and arithmetic
    — so it costs nothing against the 250/day budget.

    Rows you have edited (`source = 'user'`) are never touched. The API not
    knowing about a service you catch every day must not mean Sunday forgets it
    again every Sunday night.
    """
    import httpx
    from executors.travel_ops import (
        STOP_FINDER_URL, _coord_pair, _parse_time, headway_from_departures,
        haversine_m, _as_lonlat, _ors_geocode, _ors_route, _RAIL_CLASSES,
        _tfnsw_geocode,
    )
    from config import TFNSW_API_KEY, WALK_RADIUS_BUS_M, WALK_RADIUS_RAIL_M

    if not TFNSW_API_KEY:
        print("[nearby_services] TFNSW_API_KEY is not set; nothing to discover")
        return

    try:
        user = await resolve_user(client)
    except Exception as e:
        print(f"[nearby_services] no user: {e}")
        return
    uid = user["user_id"]

    place = row(await asyncio.to_thread(
        lambda: client.table("saved_places")
        .select("label, address, lat, lng")
        .eq("user_id", uid).eq("is_default", True).limit(1).maybe_single().execute()
    ))
    if not place:
        print("[nearby_services] no default saved place")
        return
    label = place.get("label") or "home"

    headers = {"Authorization": f"apikey {TFNSW_API_KEY}", "Accept": "application/json"}
    discovered = []

    async with httpx.AsyncClient() as http:
        # A coordinate is needed to search around and to measure walks from.
        origin_ll = None
        already_stored = (place.get("lat") is not None and place.get("lng") is not None)
        if already_stored:
            origin_ll = (float(place["lat"]), float(place["lng"]))
        else:
            address = place.get("address") or ""
            lonlat = _as_lonlat(address)
            if lonlat:
                origin_ll = (lonlat[1], lonlat[0])
            elif address:
                # TfNSW first, ORS second. stop_finder resolves a free-text
                # address using the key and client this job already needs, so
                # transit discovery does not hang on a DRIVING provider it
                # otherwise has no use for — and keeps working if the ORS key
                # lapses or hits its 2000/day cap.
                origin_ll = await _tfnsw_geocode(http, headers, address)
                if not origin_ll:
                    try:
                        lonlat = await _ors_geocode(http, address)
                        if lonlat:
                            origin_ll = (lonlat[1], lonlat[0])
                    except Exception as e:
                        print(f"[nearby_services] ORS geocode failed: {e}")

        if not origin_ll:
            print("[nearby_services] could not place the default address on the map")
            return

        # Remember it, so this is geocoded once rather than every week. Only
        # when both were empty: a coordinate someone set by hand is a decision,
        # not a cache, and must not be silently replaced by a lookup.
        if not already_stored:
            try:
                await asyncio.to_thread(
                    lambda: client.table("saved_places")
                    .update({"lat": origin_ll[0], "lng": origin_ll[1]})
                    .eq("user_id", uid).eq("is_default", True)
                    .is_("lat", "null").is_("lng", "null")
                    .execute()
                )
                print(f"[nearby_services] saved home coordinates {origin_ll[0]:.5f},{origin_ll[1]:.5f}")
            except Exception as e:
                print(f"[nearby_services] could not save coordinates: {e}")

        stops = await _find_stops(http, headers, origin_ll,
                                  max(WALK_RADIUS_BUS_M, WALK_RADIUS_RAIL_M))
        for stop in stops:
            # Rail is worth walking further for than a bus is.
            limit = (WALK_RADIUS_RAIL_M if (stop["classes"] & _RAIL_CLASSES)
                     else WALK_RADIUS_BUS_M)
            if stop["distance_m"] > limit:
                continue

            walk_min = await _walk_minutes(http, origin_ll, stop)
            for service in await _stop_services(http, headers, stop):
                discovered.append({
                    "user_id": uid, "place_label": label,
                    "stop_id": stop["id"], "stop_name": stop["name"],
                    "stop_lat": stop["lat"], "stop_lng": stop["lng"],
                    "mode_class": service["mode_class"],
                    "route": service["route"], "headsign": service["headsign"],
                    "headway_min": service["headway_min"],
                    "walk_min": walk_min,
                    "source": "discovered", "is_hidden": False,
                    "refreshed_at": datetime.now(timezone.utc).isoformat(),
                })

    if not discovered:
        print("[nearby_services] found nothing; leaving the existing inventory alone")
        return

    # Upserted one at a time against the unique index rather than deleted and
    # rewritten: a wipe-then-insert would drop is_hidden on every row, so a
    # route you retired would come back every week.
    written = 0
    first_error = None
    for record in discovered:
        try:
            await asyncio.to_thread(
                lambda r=record: client.table("nearby_services")
                .upsert(r, on_conflict="user_id,place_label,stop_name,route,headsign")
                .execute()
            )
            written += 1
        except Exception as e:
            first_error = first_error or e
            print(f"[nearby_services] could not save {record['route']} at {record['stop_name']}: {e}")

    routes = sorted({r["route"] for r in discovered})
    stops = len({r["stop_name"] for r in discovered})

    # Discovery succeeding and persistence failing on every single row is the
    # failure this job actually had, for a week: the upsert key was an
    # expression index that PostgREST cannot target, so all of these lost to
    # 42P10 while the summary line still cheerfully listed the routes it had
    # found. A per-row warning in a log nobody reads was not enough. Say
    # plainly that nothing was saved, and what it costs.
    if not written:
        print(f"[nearby_services] FOUND {len(discovered)} services at {stops} stops "
              f"({', '.join(routes[:12])}) AND SAVED NONE OF THEM. Trip planning "
              f"falls back to a single corridor until this is fixed. "
              f"First error: {first_error}")
        return

    if written < len(discovered):
        print(f"[nearby_services] {len(discovered) - written} of {len(discovered)} "
              f"services could not be saved; first error: {first_error}")

    print(f"[nearby_services] {written} services at {stops} "
          f"stops near {label}: {', '.join(routes[:12])}")


def _stops_from_locations(locations, origin_ll, radius_m) -> list:
    """EFA locations to stop records, pseudo-locations dropped. Pure.

    Distance is computed here with haversine rather than read from EFA's own
    `properties.distance`: the coordinate is already needed, the arithmetic is
    free, and it is one less field whose meaning has to be taken on trust.
    """
    from executors.travel_ops import _coord_pair, haversine_m, is_real_stop_id

    out = []
    for loc in locations or []:
        stop_id = loc.get("id")
        # The whole point. An address echoed back is not somewhere you can
        # catch a bus from, however willingly departure_mon answers for it.
        if not is_real_stop_id(stop_id):
            continue
        coord = _coord_pair(loc.get("coord"))
        if not coord:
            continue
        distance = haversine_m(origin_ll, coord)
        if distance > radius_m:
            continue
        out.append({
            "id": stop_id, "name": loc.get("name") or "",
            "lat": coord[0], "lng": coord[1], "distance_m": distance,
            "classes": set(loc.get("productClasses") or []),
        })
    out.sort(key=lambda s: s["distance_m"])
    return out


async def _find_stops(http, headers, origin_ll, radius_m) -> list:
    """Stops within `radius_m`, with their product classes and distance.

    Asks /v1/tp/coord — the endpoint whose question is "what is near this
    point" — and falls back to stop_finder.

    stop_finder was the original call, and it answers a different question.
    Given type_sf=coord it reverse-geocodes and hands back the ADDRESS as a
    single `coord:` pseudo-location, so the radius filter had nothing to filter
    and discovery attributed every route to one fake stop at the front door.
    Ten bus routes, every walk_min 0, no rail or metro ever considered. It went
    unnoticed because departure_mon answers for a coord: id with a proximity
    scan, so the routes that came back were real.

    Both paths now run through _stops_from_locations, which drops pseudo-ids —
    so the fallback cannot quietly reintroduce the bug, and a wrong guess at
    the coord parameters degrades to "found nothing" rather than to something
    plausible and wrong. refresh_nearby_services leaves the existing inventory
    alone when nothing is found, so that failure is non-destructive.
    """
    from executors.travel_ops import COORD_URL, STOP_FINDER_URL

    # EFA wants X:Y — longitude first, the opposite of everything else here.
    efa_coord = f"{origin_ll[1]}:{origin_ll[0]}:EPSG:4326"

    # type_1 selects what kind of thing to return, and the two spellings below
    # are both current in EFA deployments. Trying the second only when the
    # first yields nothing costs one extra request a week.
    for type_1 in ("STOP", "GIS_POINT"):
        params = {
            "outputFormat": "rapidJSON",
            "coordOutputFormat": "EPSG:4326",
            "coord": efa_coord,
            "inclFilter": 1,
            "type_1": type_1,
            "radius_1": int(radius_m),
            "version": "10.2.1.42",
        }
        try:
            res = await http.get(COORD_URL, headers=headers, params=params, timeout=20.0)
            res.raise_for_status()
            locations = (res.json() or {}).get("locations") or []
        except Exception as e:
            print(f"[nearby_services] coord({type_1}) failed: {e}")
            continue
        stops = _stops_from_locations(locations, origin_ll, radius_m)
        if stops:
            print(f"[nearby_services] coord({type_1}) found {len(stops)} stops")
            return stops

    params = {
        "outputFormat": "rapidJSON",
        "coordOutputFormat": "EPSG:4326",
        "type_sf": "coord",
        "name_sf": efa_coord,
        "TfNSWSF": "true",
        "version": "10.2.1.42",
    }
    try:
        res = await http.get(STOP_FINDER_URL, headers=headers, params=params, timeout=20.0)
        res.raise_for_status()
        locations = (res.json() or {}).get("locations") or []
    except Exception as e:
        print(f"[nearby_services] stop_finder failed: {e}")
        return []

    stops = _stops_from_locations(locations, origin_ll, radius_m)
    if not stops and locations:
        print(f"[nearby_services] stop_finder returned {len(locations)} location(s), "
              "none of them a real stop — the coord endpoint is the one that "
              "answers this question, and it returned nothing either.")
    return stops


async def _walk_minutes(http, origin_ll, stop):
    """Walking minutes to a stop, or a straight-line estimate if ORS is absent.

    The estimate is deliberately pessimistic — 4.5 km/h over the crow-flies
    distance, which real streets always exceed — so a missing key degrades the
    number rather than the answer. It is labelled nowhere as exact, and the
    honest alternative would be to skip the stop entirely.
    """
    from executors.travel_ops import _ors_route
    from config import OPENROUTESERVICE_API_KEY

    if OPENROUTESERVICE_API_KEY:
        minutes, _km = await _ors_route(
            http, [origin_ll[1], origin_ll[0]], [stop["lng"], stop["lat"]],
            "foot-walking")
        if minutes is not None:
            return minutes
    return int(round(stop["distance_m"] / 75.0))    # 4.5 km/h in metres/min


async def _stop_services(http, headers, stop) -> list:
    """Which routes serve a stop, where they go, and how often."""
    from executors.travel_ops import _parse_time, headway_from_departures

    params = {
        "outputFormat": "rapidJSON",
        "coordOutputFormat": "EPSG:4326",
        "mode": "direct",
        "type_dm": "stop",
        "name_dm": stop["id"],
        "departureMonitorMacro": "true",
        "TfNSWDM": "true",
        "version": "10.2.1.42",
    }
    try:
        res = await http.get(
            "https://api.transport.nsw.gov.au/v1/tp/departure_mon",
            headers=headers, params=params, timeout=20.0)
        res.raise_for_status()
        events = (res.json() or {}).get("stopEvents") or []
    except Exception as e:
        print(f"[nearby_services] departures failed for {stop['name']}: {e}")
        return []

    # Grouped by (route, where it is heading): the 358 towards Mascot and the
    # 358 back are different services to someone deciding which side of the
    # road to stand on.
    seen = {}
    for event in events:
        transport = event.get("transportation") or {}
        route = (transport.get("disassembledName") or transport.get("number") or "").strip()
        if not route:
            continue
        headsign = ((transport.get("destination") or {}).get("name") or "").strip()
        mode_class = (transport.get("product") or {}).get("class")
        when = _parse_time(event.get("departureTimePlanned")
                           or event.get("departureTimeEstimated"))
        if not when:
            continue
        seen.setdefault((route, headsign), {"mode_class": mode_class, "times": []})
        seen[(route, headsign)]["times"].append(when)

    return [
        {"route": route, "headsign": headsign,
         "mode_class": data["mode_class"],
         "headway_min": headway_from_departures(data["times"])}
        for (route, headsign), data in seen.items()
    ]
