import asyncio
from google.api_core import exceptions

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
