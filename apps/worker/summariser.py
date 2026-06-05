import asyncio
from datetime import date

from google import genai
from google.genai import types

from config import GEMINI_MODEL, GEMINI_MAX_TOKENS, GEMINI_TEMPERATURE
from executors.profile_ops import update_profile
from budget_gate import pick_model, check_and_increment

_SUMMARY_PROMPT = """You are updating a personal assistant's memory file.
Review this conversation and extract ONLY new, durable facts about the user:
preferences, habits, projects, people mentioned, decisions made, or recurring topics.
Do NOT include facts already obvious from context.
Format as bullet points under a section heading that describes the topic.
If there is nothing new worth remembering, respond with exactly: NOTHING_NEW"""


def _fetch_transcript(client, user_id: str, limit: int = 20) -> str:
    result = (
        client.table("messages")
        .select("role,content,created_at")
        .eq("user_id", user_id)
        .order("created_at", desc=False)
        .limit(limit)
        .execute()
    )
    lines = []
    for row in result.data or []:
        role = row.get("role", "unknown")
        content = (row.get("content") or "").strip()
        if content:
            lines.append(f"{role.upper()}: {content}")
    return "\n\n".join(lines)


async def _summarise_with_budget(client_db, transcript: str, gemini_api_key: str, user_id: str) -> str:
    """Summarise using the budget gate to pick and record the model."""
    model_id = await pick_model(client_db, user_id, allow_flash=False)
    if model_id == "EXHAUSTED" or model_id == "ollama":
        print("[summariser] LLM budget exhausted — skipping summarisation")
        return "NOTHING_NEW"
    
    await check_and_increment(client_db, user_id, model_id)
    
    client = genai.Client(api_key=gemini_api_key)
    response = await asyncio.to_thread(
        lambda: client.models.generate_content(
            model=model_id,
            contents=[
                types.Content(
                    role="user",
                    parts=[types.Part(text=f"{_SUMMARY_PROMPT}\n\n---\n\n{transcript}")],
                )
            ],
            config=types.GenerateContentConfig(
                max_output_tokens=GEMINI_MAX_TOKENS,
                temperature=GEMINI_TEMPERATURE,
            ),
        )
    )
    return (
        "".join(
            p.text for p in response.candidates[0].content.parts
            if hasattr(p, "text") and p.text
        ).strip()
        if response and response.candidates and response.candidates[0].content
        else "NOTHING_NEW"
    )


async def maybe_summarise(client, gemini_api_key: str, message_count: int, user_id: str) -> None:
    if message_count % 7 != 0:
        return

    if not user_id:
        print("[summariser] skipping — no user_id provided")
        return

    transcript = await asyncio.to_thread(_fetch_transcript, client, user_id)
    if not transcript:
        return

    summary = await _summarise_with_budget(client, transcript, gemini_api_key, user_id)
    if not summary or summary.strip() == "NOTHING_NEW":
        return

    section = f"Learned — {date.today().isoformat()}"
    await update_profile(section, summary)
    print(f"[summariser] profile updated: {section}")
