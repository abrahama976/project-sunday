"""Scheduled job handler functions.

Each handler has the signature:
    async def handler(client: Client, gemini_api_key: str) -> None

These are registered with the Scheduler in main.py.
"""
from datetime import date, datetime, timezone
from supabase import Client

from google import genai
from google.genai import types
from config import GEMINI_MODEL, GEMINI_MAX_TOKENS


async def morning_briefing(client: Client, gemini_api_key: str) -> None:
    """Generate the daily morning briefing.

    Composes a summary from:
    - Today's calendar events
    - Open/due tasks
    - Priority emails (if available)
    - News digest (if available)

    Stores the result in the daily_briefings table and posts
    a message to the chat.
    """
    today = date.today()
    today_str = today.isoformat()

    # Check if briefing already exists for today
    existing = (
        client.table("daily_briefings")
        .select("id")
        .eq("briefing_date", today_str)
        .maybeSingle()
        .execute()
    )
    if existing.data:
        print(f"[briefing] already generated for {today_str}")
        return

    # Gather context sections
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
        news_result = (
            client.table("news_items")
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

            # Mark as surfaced
            ids = [item["id"] for item in news_result.data if "id" in item]
            if ids:
                for nid in ids:
                    client.table("news_items").update({"surfaced": True}).eq("id", nid).execute()
        else:
            sections["news"] = "(No new items)"
    except Exception as e:
        sections["news"] = f"(News unavailable: {e})"

    # Generate briefing with Gemini
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

## News
{sections.get('news', '(No data)')}

Rules:
- Keep it brief and actionable.
- Use bullet points, not paragraphs.
- Start with a one-line summary of the day.
- If a section has "(No data)" or "(unavailable)", skip it entirely.
- Don't include the section headers if there's nothing to show."""

    try:
        ai_client = genai.Client(api_key=gemini_api_key)
        response = ai_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
            config=types.GenerateContentConfig(
                max_output_tokens=GEMINI_MAX_TOKENS,
                temperature=0.4,
            ),
        )
        content = "".join(
            p.text for p in response.candidates[0].content.parts
            if hasattr(p, "text") and p.text
        ).strip()
    except Exception as e:
        content = f"⚠️ Briefing generation failed: {e}"

    # Store in daily_briefings
    import json
    client.table("daily_briefings").insert({
        "briefing_date": today_str,
        "content": content,
        "sections": json.dumps(sections),
    }).execute()

    # Post as a chat message
    client.table("messages").insert({
        "role": "assistant",
        "content": f"☀️ **Morning Briefing — {today.strftime('%A, %d %B')}**\n\n{content}",
        "model_used": "gemini",
    }).execute()

    print(f"[briefing] generated for {today_str}")


async def email_scan(client: Client, gemini_api_key: str) -> None:
    """Periodic email scan — check for new priority emails.
    
    This runs every 30 minutes. It scans for unread important emails
    and could trigger a notification or update the dashboard.
    For now, it logs the count.
    """
    try:
        from executors.gmail_ops import gmail_priority_scan
        result = await gmail_priority_scan(max_results=5)
        import json
        try:
            emails = json.loads(result)
            count = len(emails)
        except (json.JSONDecodeError, TypeError):
            count = 0 if "No unread" in result else 1

        print(f"[email_scan] found {count} priority email(s)")
    except Exception as e:
        print(f"[email_scan] error: {e}")


async def news_fetch(client: Client, gemini_api_key: str) -> None:
    """Fetch and score RSS feeds, store relevant articles.
    
    Runs twice daily (6am, 6pm). Uses the news_ops executor
    to fetch, score, and store articles.
    """
    try:
        from executors.news_ops import news_fetch_and_store
        result = await news_fetch_and_store(client, gemini_api_key)
        print(f"[news_fetch] {result}")
    except Exception as e:
        print(f"[news_fetch] error: {e}")
