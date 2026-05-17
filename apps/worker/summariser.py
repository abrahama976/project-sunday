import asyncio
from datetime import date

from google import genai
from google.genai import types

from config import GEMINI_MODEL, GEMINI_MAX_TOKENS, GEMINI_TEMPERATURE
from executors.profile_ops import update_profile

_SUMMARY_PROMPT = """You are updating a personal assistant's memory file for Alstone.
Review this conversation and extract ONLY new, durable facts about Alstone:
preferences, habits, projects, people mentioned, decisions made, or recurring topics.
Do NOT include facts already obvious from context.
Format as bullet points under a section heading that describes the topic.
If there is nothing new worth remembering, respond with exactly: NOTHING_NEW"""


def _fetch_transcript(client, limit: int = 20) -> str:
    result = (
        client.table("messages")
        .select("role,content,created_at")
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


def _summarise_sync(transcript: str, gemini_api_key: str) -> str:
    client = genai.Client(api_key=gemini_api_key)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
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
    return "".join(
        p.text for p in response.candidates[0].content.parts if hasattr(p, "text") and p.text
    ).strip()


async def maybe_summarise(client, gemini_api_key: str, message_count: int) -> None:
    if message_count % 7 != 0:
        return

    transcript = await asyncio.to_thread(_fetch_transcript, client)
    if not transcript:
        return

    summary = await asyncio.to_thread(_summarise_sync, transcript, gemini_api_key)
    if not summary or summary.strip() == "NOTHING_NEW":
        return

    section = f"Learned — {date.today().isoformat()}"
    await update_profile(section, summary)
    print(f"[summariser] profile updated: {section}")
