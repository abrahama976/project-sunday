import asyncio
from supabase import Client

_executed: set[str] = set()

def already_executed(idempotency_key: str) -> bool:
    return idempotency_key in _executed

def mark_executed(idempotency_key: str):
    _executed.add(idempotency_key)

async def set_status(client: Client, action_id: str, status: str, error: dict = None):
    update = {"status": status}
    if error:
        update["error"] = error
    await asyncio.to_thread(lambda: client.table("action_queue").update(update).eq("id", action_id).execute())
