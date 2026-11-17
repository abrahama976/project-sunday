"""Central LLM budget gate for Project Sunday.

Every LLM call in the system — chat, brain-dump, cron jobs, summariser —
must pass through this module before making an API request.

Two entry points:
    pick_model(client, user_id)          → best available model string
    check_and_increment(client, user_id, model) → True if allowed (already incremented)

The gate calls `increment_llm_usage()` — a Postgres function that does an
atomic INSERT ... ON CONFLICT DO UPDATE ... RETURNING, so concurrent calls
never double-count or produce stale reads.

The cascade, best capability first:

    Gemini Flash → Gemini Flash-Lite → NVIDIA → Groq → Ollama → EXHAUSTED

Only the first three do tool calling. Groq and Ollama end tool use but still
answer, which is the point of degrading rather than failing. A provider may not
be placed above a tool-calling one unless it also calls tools — that rule is
why NVIDIA sits where it does and why the dead 2.0 tiers were removed instead
of being left to fail over silently.

Model IDs come from config, which reads them from the environment, so a
retirement is an .env change and not a code change.
"""

import asyncio
import time
from datetime import date

import httpx

from supabase import Client
from config import (
    GEMINI_MODEL, GEMINI_LITE_MODEL,
    DAILY_FLASH_LIMIT, GLOBAL_FLASH_CEILING,
    DAILY_LITE_LIMIT, GLOBAL_LITE_CEILING,
    DAILY_NVIDIA_LIMIT, GLOBAL_NVIDIA_CEILING, NVIDIA_RPM_LIMIT,
    OLLAMA_HOST, GROQ_API_KEY, GROQ_MODEL, NVIDIA_API_KEY, NVIDIA_MODEL,
)

# Canonical model tier names stored in the ledger
TIER_FLASH = "flash"
TIER_LITE = "lite"
TIER_NVIDIA = "nvidia"
TIER_GROQ = "groq"

# Timestamps (monotonic) of NVIDIA calls made by THIS process in the last
# minute. The daily ledger cannot express a per-minute ceiling, and the free
# endpoint throttles at roughly 40/minute; a burst of failovers is exactly the
# shape that would trip it. Process-local on purpose: the worker is one process,
# and a shared window would need a table for a guard this cheap.
_nvidia_calls: list[float] = []


def _model_to_tier(model: str) -> str:
    """Map a model string to its ledger tier.

    Exact configured IDs are matched first. The old substring heuristic filed
    anything containing "llama" under Groq, which would have given an NVIDIA
    model Groq's uncapped budget the moment one was configured.
    """
    if model == GEMINI_MODEL:
        return TIER_FLASH
    if model == GEMINI_LITE_MODEL:
        return TIER_LITE
    if model == NVIDIA_MODEL or (isinstance(model, str) and "/" in model):
        return TIER_NVIDIA
    if model == GROQ_MODEL:
        return TIER_GROQ

    m = model.lower()
    if "lite" in m:
        return TIER_LITE
    if "groq" in m or "llama" in m:
        return TIER_GROQ
    return TIER_FLASH  # default: the primary Gemini Flash tier


def _tier_limits(tier: str) -> tuple[int, int]:
    if tier == TIER_LITE:
        return DAILY_LITE_LIMIT, GLOBAL_LITE_CEILING
    if tier == TIER_NVIDIA:
        return DAILY_NVIDIA_LIMIT, GLOBAL_NVIDIA_CEILING
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


def _nvidia_available() -> bool:
    """Return True if an NVIDIA_API_KEY is configured."""
    return bool(NVIDIA_API_KEY)


def _nvidia_rpm_ok(now: float | None = None) -> bool:
    """True while this process is under the per-minute NVIDIA ceiling."""
    now = time.monotonic() if now is None else now
    cutoff = now - 60.0
    while _nvidia_calls and _nvidia_calls[0] < cutoff:
        _nvidia_calls.pop(0)
    return len(_nvidia_calls) < NVIDIA_RPM_LIMIT


def _note_nvidia_call(now: float | None = None) -> None:
    _nvidia_calls.append(time.monotonic() if now is None else now)


def _reset_nvidia_rpm() -> None:
    """Test hook: forget the calls recorded in this process."""
    _nvidia_calls.clear()


async def pick_model(client: Client, user_id: str, allow_flash: bool = True) -> str:
    """Return the best available model for this user right now.

    Cascade (highest quality first):
      Flash (if allow_flash) → Flash-Lite → NVIDIA → Groq → Ollama → 'EXHAUSTED'

    NVIDIA is skipped when it has no key, when the last minute is already full,
    or when its daily ledger is at the cap — all three are ordinary states, not
    errors. Ollama is last because it does not call tools here.

    Does NOT increment — caller must call check_and_increment() after choosing.
    """
    if allow_flash:
        if await get_usage(client, user_id, TIER_FLASH) < DAILY_FLASH_LIMIT:
            return GEMINI_MODEL
    if await get_usage(client, user_id, TIER_LITE) < DAILY_LITE_LIMIT:
        return GEMINI_LITE_MODEL
    if (
        _nvidia_available()
        and _nvidia_rpm_ok()
        and await get_usage(client, user_id, TIER_NVIDIA) < DAILY_NVIDIA_LIMIT
    ):
        _note_nvidia_call()
        return NVIDIA_MODEL
    if _groq_available():
        return GROQ_MODEL
    if await _probe_ollama():
        return "ollama"
    return "EXHAUSTED"
