"""Scheduled job handler functions.

Each handler has the signature:
    async def handler(client: Client, gemini_api_key: str) -> None

These are registered with the Scheduler in main.py.
"""
import asyncio
from datetime import date, datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from supabase import Client
import json
import gzip
import io

from google import genai
from google.genai import types
from config import GEMINI_MODEL, GEMINI_MAX_TOKENS


async def morning_briefing(client: Client, gemini_api_key: str) -> None:
    """Generate the daily morning briefing."""
    today = date.today()
    today_str = today.isoformat()

    existing = await asyncio.to_thread(
        lambda: client.table("daily_briefings")
        .select("id")
        .eq("briefing_date", today_str)
        .maybeSingle()
        .execute()
    )
    if existing.data:
        print(f"[briefing] already generated for {today_str}")
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

    # 4. News (if items exist)
    try:
        news_result = await asyncio.to_thread(
            lambda: client.table("news_items")
            .select("title,source,summary,url")
            .eq("surfaced", False)
            .order("relevance", desc=True)
            .limit(5)
            .execute()
        )
        if news_result.data:
            news_lines = []
            for item in news_result.data:
                news_lines.append(f"- {item['title']} ({item.get('source', 'unknown')})")
            sections["news"] = "\n".join(news_lines)

            ids = [item["id"] for item in news_result.data if "id" in item]
            if ids:
                for nid in ids:
                    await asyncio.to_thread(lambda: client.table("news_items").update({"surfaced": True}).eq("id", nid).execute())
        else:
            sections["news"] = "(No new items)"
    except Exception as e:
        sections["news"] = f"(News unavailable: {e})"

    # 5. Web Search fallback for requested regions
    try:
        from executors.web_search_ops import web_search
        search_queries = ["Top news today Sydney Australia", "Top news today India", "Top news today Oman", "Top news today Singapore"]
        search_results = []
        for q in search_queries:
            try:
                res = await web_search(q)
                search_results.append(f"### {q}\n{res}")
            except Exception as e:
                search_results.append(f"### {q}\nFailed: {e}")
        sections["web_news"] = "\n\n".join(search_results)
    except Exception as e:
        sections["web_news"] = f"(Web news unavailable: {e})"

    prompt = f"""You are Project Sunday, generating a morning briefing for Alstone.
Today is {today.strftime('%A, %d %B %Y')}.

Compose a concise, useful daily briefing in markdown format.
Include these sections (skip any that have no data):

## Schedule
{sections.get('schedule', '(No data)')}

## Tasks Due
{sections.get('tasks', '(No data)')}

## Priority Emails
{sections.get('emails', '(No data)')}

## RSS News
{sections.get('news', '(No data)')}

## Regional Web News
{sections.get('web_news', '(No data)')}

Rules:
- Keep it brief and actionable.
- Use bullet points, not paragraphs.
- Start with a one-line summary of the day.
- If a section has "(No data)" or "(unavailable)", skip it entirely.
- Don't include the section headers if there's nothing to show."""

    try:
        ai_client = genai.Client(api_key=gemini_api_key)
        response = await asyncio.to_thread(
            lambda: ai_client.models.generate_content(
                model=GEMINI_MODEL,
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
            "briefing_date": today_str,
            "content": content,
            "sections": json.dumps(sections),
        }).execute()
    )

    await asyncio.to_thread(
        lambda: client.table("messages").insert({
            "role": "assistant",
            "content": f"☀️ **Morning Briefing — {today.strftime('%A, %d %B')}**\n\n{content}",
            "model_used": "gemini",
        }).execute()
    )
    print(f"[briefing] generated for {today_str}")


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


async def news_fetch(client: Client, gemini_api_key: str) -> None:
    try:
        from executors.news_ops import news_fetch_and_store
        result = await news_fetch_and_store(client, gemini_api_key)
        print(f"[news_fetch] {result}")
    except Exception as e:
        print(f"[news_fetch] error: {e}")


async def meal_checkin(client: Client, gemini_api_key: str) -> None:
    loc_result = await asyncio.to_thread(
        lambda: client.table("user_location").select("timezone").limit(1).maybeSingle().execute()
    )
    tz_str = loc_result.data.get("timezone", "Australia/Sydney") if loc_result.data else "Australia/Sydney"
    now = datetime.now(ZoneInfo(tz_str))

    try:
        from executors.calendar_ops import calendar_query
        events_str = await calendar_query(query="", days_ahead=1)
        
        prompt = f"""You are checking Alstone's schedule to see if he has a free 15-minute gap in the next 2 hours to eat.
Current time: {now.strftime('%Y-%m-%d %H:%M')}

Schedule:
{events_str}

Is there a free 15-minute window in the next 2 hours? Reply YES or NO only."""

        ai_client = genai.Client(api_key=gemini_api_key)
        response = await asyncio.to_thread(
            lambda: ai_client.models.generate_content(
                model=GEMINI_MODEL,
                contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
                config=types.GenerateContentConfig(max_output_tokens=10, temperature=0.1),
            )
        )
        ans = response.candidates[0].content.parts[0].text.strip().upper()
        if "YES" in ans:
            msg = "Hey, it looks like you have a moment — did you eat? Let me log it for you."
            await asyncio.to_thread(
                lambda: client.table("messages").insert({
                    "role": "assistant",
                    "content": msg,
                    "model_used": "system",
                }).execute()
            )
            print("[meal_checkin] sent proactive check-in")
            
            # Delete any existing retry
            await asyncio.to_thread(
                lambda: client.table("scheduled_jobs").delete().eq("job_name", "meal_checkin_retry").execute()
            )
        else:
            print("[meal_checkin] no free window, silently skipping and scheduling retry")
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
        print(f"[meal_checkin] failed: {e}")


async def nightly_maintenance(client: Client, gemini_api_key: str) -> None:
    print("[nightly_maintenance] starting")
    now_utc = datetime.now(timezone.utc)
    
    # 1. Archive tasks > 7 days old
    try:
        cutoff_7 = (now_utc - timedelta(days=7)).isoformat()
        await asyncio.to_thread(
            lambda: client.table("tasks")
            .update({"is_archived": True})
            .eq("status", "done")
            .lt("completed_at", cutoff_7)
            .execute()
        )
    except Exception as e:
        print(f"[nightly_maintenance] tasks error: {e}")

    # 2. Delete health_logs > 30 days old
    try:
        cutoff_30 = (now_utc - timedelta(days=30)).date().isoformat()
        await asyncio.to_thread(
            lambda: client.table("health_logs")
            .delete()
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
            
            ai_client = genai.Client(api_key=gemini_api_key)
            response = await asyncio.to_thread(
                lambda: ai_client.models.generate_content(
                    model="gemini-2.5-flash-lite",
                    contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
                    config=types.GenerateContentConfig(max_output_tokens=1000)
                )
            )
            summary = "".join(p.text for p in response.candidates[0].content.parts if hasattr(p, "text") and p.text).strip()
            
            await asyncio.to_thread(
                lambda: client.table("message_summaries").insert({
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
            print(f"[nightly_maintenance] compressed {len(msgs)} messages")
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

        loc_result = await asyncio.to_thread(
            lambda: client.table("user_location").select("lat, lng").limit(1).maybeSingle().execute()
        )
        loc_data = loc_result.data or {}
        origin_lat = loc_data.get("lat")
        origin_lng = loc_data.get("lng")

        ai_client = genai.Client(api_key=gemini_api_key)
        
        prompt_extract = f"""Extract a JSON array of events from this calendar string.
Each object must have 'title', 'location', and 'needs_prep' (boolean, true if there are attendees or it's a meeting).
Calendar string:
{events_str}
Return ONLY valid JSON (no markdown block)."""
        
        response_ext = await asyncio.to_thread(
            lambda: ai_client.models.generate_content(
                model=GEMINI_MODEL,
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
                    from executors.travel_ops import travel_directions
                    origin_str = f"{origin_lat},{origin_lng}"
                    travel_result = await travel_directions(origin=origin_str, destination=dest, mode="transit")
                    
                    if "No directions" not in travel_result:
                        await asyncio.to_thread(
                            lambda: client.table("tasks").insert({
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
        if not uid: continue
        sample = utasks[:2]
        task_titles = [t["title"] for t in sample]
        
        prompt = f"""You are Project Sunday. The user has these open tasks they haven't been nudged about in a while:
{json.dumps(task_titles)}

Write a very short, casual 1-sentence nudge for the chat interface. Be friendly. No robotic language."""

        try:
            ai_client = genai.Client(api_key=gemini_api_key)
            response = await asyncio.to_thread(
                lambda: ai_client.models.generate_content(
                    model="gemini-2.5-flash",
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
                    "model_used": "gemini"
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
        # 1. Archive Messages
        msg_res = await asyncio.to_thread(
            lambda: client.table("messages")
            .select("*")
            .eq("is_deleted", True)
            .lt("created_at", cutoff_30)
            .execute()
        )
        msgs = msg_res.data or []
        
        # 2. Archive Tasks
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
            
        archive_data = {
            "archived_at": now_utc.isoformat(),
            "messages": msgs,
            "tasks": tasks
        }
        
        json_bytes = json.dumps(archive_data).encode('utf-8')
        compressed = gzip.compress(json_bytes)
        
        filename = f"archive_{now_utc.strftime('%Y%m%d_%H%M%S')}.json.gz"
        
        # Upload to cold_archive
        await asyncio.to_thread(
            lambda: client.storage.from_("cold_archive").upload(
                path=filename,
                file=compressed,
                file_options={"content-type": "application/gzip"}
            )
        )
        print(f"[cold_storage_archive] Uploaded {filename} to Storage")
        
        # Hard delete
        if msgs:
            msg_ids = [m["id"] for m in msgs]
            # Delete in chunks of 100
            for i in range(0, len(msg_ids), 100):
                chunk = msg_ids[i:i+100]
                await asyncio.to_thread(
                    lambda: client.table("messages").delete().in_("id", chunk).execute()
                )
        if tasks:
            task_ids = [t["id"] for t in tasks]
            for i in range(0, len(task_ids), 100):
                chunk = task_ids[i:i+100]
                await asyncio.to_thread(
                    lambda: client.table("tasks").delete().in_("id", chunk).execute()
                )
                
        print(f"[cold_storage_archive] Hard deleted {len(msgs)} messages and {len(tasks)} tasks")
    except Exception as e:
        print(f"[cold_storage_archive] error: {e}")
