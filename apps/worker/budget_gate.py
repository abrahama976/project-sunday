"""Central LLM budget gate for Project Sunday.

Every LLM call in the system — chat, brain-dump, cron jobs, summariser —
must pass through this module before making an API request.

Two entry points:
    pick_model(client, user_id)          → best available model string
    check_and_increment(client, user_id, model) → True if allowed (already incremented)

The gate calls `increment_llm_usage()` — a Postgres function that does an
atomic INSERT ... ON CONFLICT DO UPDATE ... RETURNING, so concurrent calls
never double-count or produce stale reads.
"""

import asyncio
from datetime import date

import httpx

from supabase import Client
from config import (
    GEMINI_MODEL, GEMINI_LITE_MODEL, GEMINI_FLASH2_MODEL, GEMINI_FLASH15_MODEL,
    DAILY_FLASH_LIMIT, GLOBAL_FLASH_CEILING,
    DAILY_LITE_LIMIT, GLOBAL_LITE_CEILING,
    DAILY_FLASH2_LIMIT, GLOBAL_FLASH2_CEILING,
    DAILY_FLASH15_LIMIT, GLOBAL_FLASH15_CEILING,
    OLLAMA_HOST, GROQ_API_KEY, GROQ_MODEL,
)

# Canonical model tier names stored in the ledger
TIER_FLASH = "flash"
TIER_LITE = "lite"
TIER_FLASH2 = "flash2"
TIER_FLASH15 = "flash15"
TIER_GROQ = "groq"

def _model_to_tier(model: str) -> str:
    m = model.lower()
    if "lite" in m:
        return TIER_LITE
    if "2.0" in m or "flash2" in m:
        return TIER_FLASH2
    if "1.5" in m or "flash15" in m:
        return TIER_FLASH15
    if "groq" in m or "llama" in m:
        return TIER_GROQ
    return TIER_FLASH  # default: 2.5 flash

def _tier_limits(tier: str) -> tuple[int, int]:
    if tier == TIER_LITE:
        return DAILY_LITE_LIMIT, GLOBAL_LITE_CEILING
    if tier == TIER_FLASH2:
        return DAILY_FLASH2_LIMIT, GLOBAL_FLASH2_CEILING
    if tier == TIER_FLASH15:
        return DAILY_FLASH15_LIMIT, GLOBAL_FLASH15_CEILING
    if tier == TIER_GROQ:
        return 9999, 9999  # Groq free tier is generous; no hard local cap
    return DAILY_FLASH_LIMIT, GLOBAL_FLASH_CEILING


async def get_usage(client: Client, user_id: str, tier: str) -> int:
    """Read current usage for a user+tier today without incrementing."""
    today = date.today().isoformat()
    res = await asyncio.to_thread(
        lambda: client.rpc("get_llm_usage", {
            "p_user_id": user_id,
            "p_date": today,
            "p_model": tier,
        }).execute()
    )
    return res.data if isinstance(res.data, int) else 0


async def check_and_increment(client: Client, user_id: str, model: str) -> bool:
    """Atomically increment the ledger and return True if within budget.

    Passes the daily and global caps directly to the Postgres RPC, which
    enforces them transactionally and returns -1 if a cap is reached.
    """
    tier = _model_to_tier(model)
    daily_cap, global_cap = _tier_limits(tier)
    today = date.today().isoformat()

    res = await asyncio.to_thread(
        lambda: client.rpc("increment_llm_usage", {
            "p_user_id": user_id,
            "p_date": today,
            "p_model": tier,
            "p_daily_cap": daily_cap,
            "p_global_cap": global_cap,
        }).execute()
    )
    new_count = res.data if isinstance(res.data, int) else -1
    return new_count > 0


async def _probe_ollama() -> bool:
    """Check if Ollama is running and responsive."""
    try:
        async with httpx.AsyncClient() as hc:
            r = await hc.get(f"{OLLAMA_HOST}/api/version", timeout=1.0)
            return r.status_code == 200
    except Exception:
        return False

def _groq_available() -> bool:
    """Return True if a GROQ_API_KEY is configured."""
    return bool(GROQ_API_KEY)

async def pick_model(client: Client, user_id: str, allow_flash: bool = True) -> str:
    """Return the best available model for this user right now.
    Cascade (highest quality first):
      Flash 2.5 (if allow_flash) → Flash 2.5 Lite → Flash 2.0 → Flash 1.5
      → Groq (if key configured) → Ollama (if online) → 'EXHAUSTED'
    Does NOT increment — caller must call check_and_increment() after choosing.
    """
    if allow_flash:
        if await get_usage(client, user_id, TIER_FLASH) < DAILY_FLASH_LIMIT:
            return GEMINI_MODEL
    if await get_usage(client, user_id, TIER_LITE) < DAILY_LITE_LIMIT:
        return GEMINI_LITE_MODEL
    if await get_usage(client, user_id, TIER_FLASH2) < DAILY_FLASH2_LIMIT:
        return GEMINI_FLASH2_MODEL
    if await get_usage(client, user_id, TIER_FLASH15) < DAILY_FLASH15_LIMIT:
        return GEMINI_FLASH15_MODEL
    if _groq_available():
        return GROQ_MODEL  # "llama-3.3-70b-versatile"
    if await _probe_ollama():
        return "ollama"
    return "EXHAUSTED"
