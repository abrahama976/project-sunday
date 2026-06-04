import re

with open("apps/worker/jobs.py", "r") as f:
    content = f.read()

# 1. morning_briefing
morning_briefing_new = """async def morning_briefing(client: Client, gemini_api_key: str) -> None:
    \"\"\"Generate the daily morning briefing.\"\"\"
    today = date.today()
    today_str = today.isoformat()

    users_res = await asyncio.to_thread(lambda: client.rpc("get_active_users").execute())
    users = users_res.data or []

    for user in users:
        uid = user.get("user_id")
        email = user.get("email") or ""
        name = user.get("name") or (email.split("@")[0] if email else "User")
        
        if not uid:
            continue

        existing = await asyncio.to_thread(
            lambda: client.table("daily_briefings")
            .select("id")
            .eq("user_id", uid)
            .eq("briefing_date", today_str)
            .maybe_single()
            .execute()
        )
        if existing.data:
            print(f"[briefing] already generated for {name} on {today_str}")
            continue

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
                .select("id,title,source,summary,url")
                .eq("user_id", uid)
                .eq("surfaced", False)
                .order("relevance", desc=True)
                .limit(5)
                .execute()
            )
            if news_result.data:
                news_lines = []
                for item in news_result.data:
                    news_lines.append(f"- {item['title']} ({item.get('source', 'unknown')})")
                sections["news"] = "\\n".join(news_lines)

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
                    search_results.append(f"### {q}\\n{res}")
                except Exception as e:
                    search_results.append(f"### {q}\\nFailed: {e}")
            sections["web_news"] = "\\n\\n".join(search_results)
        except Exception as e:
            sections["web_news"] = f"(Web news unavailable: {e})"

        prompt = f\"\"\"You are Project Sunday, generating a morning briefing for {name}.
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
- Don't include the section headers if there's nothing to show.\"\"\"

        try:
            ai_client = genai.Client(api_key=gemini_api_key)
            model_id = await pick_model(client, uid, allow_flash=False)
            if model_id == "EXHAUSTED" or model_id == "ollama":
                content = "⚠️ Briefing generation skipped: LLM budget exhausted."
            else:
                await check_and_increment(client, uid, model_id)
                response = await asyncio.to_thread(
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
                "content": f"☀️ **Morning Briefing — {today.strftime('%A, %d %B')}**\\n\\n{content}",
                "model_used": "gemini",
            }).execute()
        )
        print(f"[briefing] generated for {name} on {today_str}")"""

content = re.sub(r'async def morning_briefing\(.*?print\(f"\[briefing\] generated for \{today_str\}"\)', morning_briefing_new, content, flags=re.DOTALL)


# 2. meal_checkin
meal_checkin_new = """async def meal_checkin(client: Client, gemini_api_key: str) -> None:
    users_res = await asyncio.to_thread(lambda: client.rpc("get_active_users").execute())
    users = users_res.data or []

    for user in users:
        uid = user.get("user_id")
        if not uid: continue
        
        name = user.get("name") or (user.get("email", "").split("@")[0] if user.get("email") else "User")

        loc_result = await asyncio.to_thread(
            lambda: client.table("user_location").select("timezone").eq("user_id", uid).limit(1).maybe_single().execute()
        )
        tz_str = loc_result.data.get("timezone", "Australia/Sydney") if loc_result.data else "Australia/Sydney"
        now = datetime.now(ZoneInfo(tz_str))

        try:
            from executors.calendar_ops import calendar_query
            events_str = await calendar_query(query="", days_ahead=1)
            
            prompt = f\"\"\"You are checking {name}'s schedule to see if they have a free 15-minute gap in the next 2 hours to eat.
Current time: {now.strftime('%Y-%m-%d %H:%M')}

Schedule:
{events_str}

Is there a free 15-minute window in the next 2 hours? Reply YES or NO only.\"\"\"

            model_id = await pick_model(client, uid, allow_flash=False)
            if model_id == "EXHAUSTED" or model_id == "ollama":
                print(f"[meal_checkin] LLM budget exhausted for {name} — skipping")
                continue
            await check_and_increment(client, uid, model_id)

            ai_client = genai.Client(api_key=gemini_api_key)
            response = await asyncio.to_thread(
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
            print(f"[meal_checkin] failed for {name}: {e}")"""

content = re.sub(r'async def meal_checkin\(.*?print\(f"\[meal_checkin\] failed: \{e\}"\)', meal_checkin_new, content, flags=re.DOTALL)


# 3. nightly_maintenance
nightly_new = """async def nightly_maintenance(client: Client, gemini_api_key: str) -> None:
    print("[nightly_maintenance] starting")
    now_utc = datetime.now(timezone.utc)
    
    users_res = await asyncio.to_thread(lambda: client.rpc("get_active_users").execute())
    users = users_res.data or []

    for user in users:
        uid = user.get("user_id")
        if not uid: continue
        
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

        # 2. Delete health_logs > 30 days old
        try:
            cutoff_30 = (now_utc - timedelta(days=30)).date().isoformat()
            await asyncio.to_thread(
                lambda: client.table("health_logs")
                .delete()
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
                prompt = "Summarise the following conversation into a single, concise paragraph capturing the key topics, tasks, and context discussed.\\n\\n" + "\\n".join(text_lines)
                
                # Budget gate for nightly summarisation
                model_id = await pick_model(client, uid, allow_flash=False)
                if model_id == "EXHAUSTED" or model_id == "ollama":
                    print("[nightly_maintenance] LLM budget exhausted — skipping summarisation")
                else:
                    await check_and_increment(client, uid, model_id)
                    ai_client = genai.Client(api_key=gemini_api_key)
                    response = await asyncio.to_thread(
                        lambda: ai_client.models.generate_content(
                            model=model_id,
                            contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
                            config=types.GenerateContentConfig(max_output_tokens=1000)
                        )
                    )
                    summary = "".join(p.text for p in response.candidates[0].content.parts if hasattr(p, "text") and p.text).strip()
                
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
            print(f"[nightly_maintenance] messages error: {e}")"""

content = re.sub(r'async def nightly_maintenance\(.*?print\(f"\[nightly_maintenance\] messages error: \{e\}"\)', nightly_new, content, flags=re.DOTALL)


# 4. calendar_prep
calendar_prep_new = """async def calendar_prep(client: Client, gemini_api_key: str) -> None:
    print("[calendar_prep] starting")
    try:
        from executors.calendar_ops import calendar_query
        events_str = await calendar_query(query="", days_ahead=1)
        if "No events found" in events_str:
            print("[calendar_prep] No events to prep for today.")
            return

        users_res = await asyncio.to_thread(lambda: client.rpc("get_active_users").execute())
        users = users_res.data or []

        for user in users:
            uid = user.get("user_id")
            if not uid: continue
            
            loc_result = await asyncio.to_thread(
                lambda: client.table("user_location").select("lat, lng").eq("user_id", uid).limit(1).maybe_single().execute()
            )
            loc_data = loc_result.data or {}
            origin_lat = loc_data.get("lat")
            origin_lng = loc_data.get("lng")

            model_id = await pick_model(client, uid, allow_flash=False)
            if model_id == "EXHAUSTED" or model_id == "ollama":
                print("[calendar_prep] LLM budget exhausted — skipping")
                continue
            await check_and_increment(client, uid, model_id)

            ai_client = genai.Client(api_key=gemini_api_key)
            
            prompt_extract = f\"\"\"Extract a JSON array of events from this calendar string.
Each object must have 'title', 'location', and 'needs_prep' (boolean, true if there are attendees or it's a meeting).
Calendar string:
{events_str}
Return ONLY valid JSON (no markdown block).\"\"\"
            
            response_ext = await asyncio.to_thread(
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
                        from executors.travel_ops import travel_directions
                        origin_str = f"{origin_lat},{origin_lng}"
                        travel_result = await travel_directions(origin=origin_str, destination=dest, mode="transit")
                        
                        if "No directions" not in travel_result:
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
        print(f"[calendar_prep] failed: {e}")"""

content = re.sub(r'async def calendar_prep\(.*?print\(f"\[calendar_prep\] failed: \{e\}"\)', calendar_prep_new, content, flags=re.DOTALL)


# 5. task_tracker -> replace pick_model with allow_flash=False + EXHAUSTED handling
content = content.replace(
    """            # Budget gate for task_tracker (per-user)
            model_id = await pick_model(client, uid)
            if model_id == "ollama":""",
    """            # Budget gate for task_tracker (per-user)
            model_id = await pick_model(client, uid, allow_flash=False)
            if model_id == "EXHAUSTED" or model_id == "ollama":"""
)

with open("apps/worker/jobs.py", "w") as f:
    f.write(content)
