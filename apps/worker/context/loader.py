"""Synchronous caches for anything injected into the system prompt.

router.build_system_prompt() is called on the hot path and is not async, so
both the profile and the learned directives are cached in module state and
refreshed explicitly — on worker start, and after any write that changes them.
"""
from supabase import Client

_cache: str = ""
_directives: list[dict] = []


def fetch_and_cache_profile(client: Client) -> str:
    """Fetches the profile from Supabase and caches it for synchronous router usage."""
    global _cache
    res = client.table("user_profile").select("content").limit(1).execute()
    if res.data:
        _cache = res.data[0].get("content", "")
    else:
        _cache = ""
    return _cache


def get_profile() -> str:
    return _cache


async def fetch_and_cache_directives(client: Client, user_id: str) -> list[dict]:
    """Refresh the cached active directive set for a user.

    Async because every caller is already in async context and this runs after
    writes; the DB call is pushed to a thread to avoid blocking the loop.
    """
    global _directives
    import asyncio

    try:
        res = await asyncio.to_thread(
            lambda: client.table("brain_directives")
            .select("id, directive, scope, weight")
            .eq("user_id", user_id)
            .eq("active", True)
            .order("weight", desc=True)
            .order("created_at", desc=False)
            .execute()
        )
        _directives = res.data or []
    except Exception as e:
        # A brain that cannot be read must never take the worker down — the
        # assistant simply runs without learned directives this cycle.
        print(f"[brain] could not load directives: {e}")
        _directives = []
    return _directives


def get_directives() -> list[dict]:
    return _directives
