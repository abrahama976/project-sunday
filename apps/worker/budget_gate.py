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

from supabase import Client
from config import (
    GEMINI_MODEL,
    GEMINI_LITE_MODEL,
    DAILY_FLASH_LIMIT,
    DAILY_LITE_LIMIT,
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

def _tier_limit(tier: str) -> int:
    if tier == TIER_LITE:
        return DAILY_LITE_LIMIT
    return DAILY_FLASH_LIMIT


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

    If the increment would exceed the daily cap, the increment still lands
    (so the count reflects the attempt), but False is returned to signal
    the caller to downgrade.  This is safe: the next call to pick_model()
    will see the over-budget tier and skip it.
    """
    tier = _model_to_tier(model)
    limit = _tier_limit(tier)
    today = date.today().isoformat()

    res = await asyncio.to_thread(
        lambda: client.rpc("increment_llm_usage", {
            "p_user_id": user_id,
            "p_date": today,
            "p_model": tier,
        }).execute()
    )
    new_count = res.data if isinstance(res.data, int) else 0
    return new_count <= limit


async def pick_model(client: Client, user_id: str) -> str:
    """Return the best available model for this user right now.

    Cascade: Flash → Lite → 'ollama'.
    Does NOT increment — the caller must call check_and_increment() after
    choosing, or use call_with_budget() for a convenient wrapper.
    """
    flash_usage = await get_usage(client, user_id, TIER_FLASH)
    if flash_usage < DAILY_FLASH_LIMIT:
        return GEMINI_MODEL  # "gemini-2.5-flash"

    lite_usage = await get_usage(client, user_id, TIER_LITE)
    if lite_usage < DAILY_LITE_LIMIT:
        return GEMINI_LITE_MODEL  # "gemini-2.5-flash-lite"

    return "ollama"
