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
    GEMINI_MODEL,
    GEMINI_LITE_MODEL,
    DAILY_FLASH_LIMIT,
    GLOBAL_FLASH_CEILING,
    DAILY_LITE_LIMIT,
    GLOBAL_LITE_CEILING,
    OLLAMA_HOST,
)

# Canonical model tier names stored in the ledger
TIER_FLASH = "flash"
TIER_LITE = "lite"

def _model_to_tier(model: str) -> str:
    """Map a model ID string to a ledger tier name."""
    m = model.lower()
    if "lite" in m:
        return TIER_LITE
    # Everything else from Gemini counts as flash
    return TIER_FLASH

def _tier_limits(tier: str) -> tuple[int, int]:
    """Return (daily_cap, global_ceiling) for a tier."""
    if tier == TIER_LITE:
        return DAILY_LITE_LIMIT, GLOBAL_LITE_CEILING
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


async def pick_model(client: Client, user_id: str, allow_flash: bool = True) -> str:
    """Return the best available model for this user right now.

    Cascade: Flash (if allow_flash) → Lite → 'ollama' (if online) → 'EXHAUSTED'.
    Does NOT increment — the caller must call check_and_increment() after choosing.
    """
    if allow_flash:
        flash_usage = await get_usage(client, user_id, TIER_FLASH)
        if flash_usage < DAILY_FLASH_LIMIT:
            return GEMINI_MODEL  # "gemini-2.5-flash"

    lite_usage = await get_usage(client, user_id, TIER_LITE)
    if lite_usage < DAILY_LITE_LIMIT:
        return GEMINI_LITE_MODEL  # "gemini-2.5-flash-lite"

    if await _probe_ollama():
        return "ollama"

    return "EXHAUSTED"
