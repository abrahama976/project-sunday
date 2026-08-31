import asyncio
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
