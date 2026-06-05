import asyncio
from supabase import Client

async def set_status(client: Client, action_id: str, status: str, error: dict = None):
    update = {"status": status}
    if error:
        update["error"] = error
    await asyncio.to_thread(lambda: client.table("action_queue").update(update).eq("id", action_id).execute())
