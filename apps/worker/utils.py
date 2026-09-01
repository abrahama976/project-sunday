import asyncio
import re

from google.api_core import exceptions


def row(result) -> dict:
    """The single row from a `.maybe_single().execute()`, or an empty dict.

    supabase-py returns **None** — not a response object with `data=None` —
    when maybe_single() matches no row. So the obvious `res.data` throws
    `'NoneType' object has no attribute 'data'` the moment a lookup misses.
    That was the live calendar_prep crash: a user with no `user_location` row.

    Every maybe_single() call site goes through this. Two sites in jobs.py had
    already grown their own `(res and res.data)` guard, which is the same fix
    discovered the hard way and applied in only one place.
    """
    if result is None:
        return {}
    return getattr(result, "data", None) or {}

# The profile editor writes the name into the markdown blob, not the column.
_NAME_LINE = re.compile(r"^\*\*Name:\*\*\s*(.+?)\s*$", re.MULTILINE)


def display_name(profile: dict, fallback: str = "there") -> str:
    """The user's first name, from wherever the profile actually keeps it.

    `user_profile.name` is the obvious place and is NULL in practice — the name
    lives in `content` as `**Name:** …`. Reading only the column is what put
    **"Good morning, None"** at the top of the daily brief every morning:
    `.get("name", "there")` returns its default when the *key* is missing, not
    when the value is NULL, so the None went straight into the f-string.

    Returns the first name only. Every caller is a greeting.
    """
    name = (profile.get("name") or "").strip()
    if not name:
        match = _NAME_LINE.search(profile.get("content") or "")
        name = match.group(1).strip() if match else ""
    return name.split()[0] if name else fallback


class MultipleUsers(RuntimeError):
    """More than one user exists, and this worker is built for exactly one.

    Raised rather than quietly serving the first. Every scheduled job used to
    fan out over `get_active_users()`; those loops are gone, so a second user
    signing up would otherwise get silence — no brief, no calendar prep, no
    task nudges — with nothing in the log to say why.
    """


async def resolve_user(client) -> dict:
    """The single user this worker serves: `{user_id, name, content}`.

    Phase 3 cut the two-user constraint on the evidence that `auth.users` holds
    exactly one row. This is the one place that assumption is checked, so if it
    ever stops being true the failure is loud and in one spot.

    Note this reads `user_profile` rather than the `get_active_users()` RPC.
    The RPC returns `user_profile.name`, which is NULL, and no `content` — so
    callers fell back to the email prefix and greeted the user as their login.
    """
    res = await asyncio.to_thread(
        lambda: client.table("user_profile").select("user_id, name, content").execute()
    )
    profiles = [p for p in (getattr(res, "data", None) or []) if p.get("user_id")]

    if len(profiles) > 1:
        raise MultipleUsers(
            f"{len(profiles)} user profiles found; this worker serves one. "
            "Restore the per-user fan-out in jobs.py before adding a second user."
        )
    if not profiles:
        raise MultipleUsers("No user profile found — nothing to run jobs for.")

    profile = profiles[0]
    return {
        "user_id": profile["user_id"],
        "name": display_name(profile),
        "content": profile.get("content") or "",
    }


async def generate_with_retry(fn, max_retries=3, base_delay=2.0):
    """
    Executes a synchronous LLM call (fn) in a thread and retries with exponential backoff
    on ResourceExhausted (429) or ServiceUnavailable (503) errors.
    """
    for attempt in range(max_retries):
        try:
            return await asyncio.to_thread(fn)
        except (exceptions.ResourceExhausted, exceptions.ServiceUnavailable) as e:
            if attempt == max_retries - 1:
                raise
            delay = base_delay * (2 ** attempt)
            print(f"[llm_retry] attempt {attempt+1} failed: {e}. Retrying in {delay}s", flush=True)
            await asyncio.sleep(delay)
