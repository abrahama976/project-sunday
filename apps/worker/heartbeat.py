import asyncio
from supabase import Client
from version import VERSION

async def run_heartbeat(client: Client, interval: int = 60):
    # `version` rides along with the liveness signal rather than being written
    # once at startup: a heartbeat that says "online" without saying what is
    # online answers half the question, and the half it omits cost an hour of
    # debugging fixes that were merged and not running.
    while True:
        try:
            await asyncio.to_thread(
                lambda: client.table("mac_heartbeat").upsert(
                    {"id": 1, "last_seen": "now()", "status": "online",
                     "version": VERSION}
                ).execute()
            )
        except Exception as e:
            print(f"[heartbeat] error: {e}")
            
        # Keep-alive: prevents TCP connection reset on idle Mac networks
        try:
            await asyncio.to_thread(
                lambda: client.table("mac_heartbeat").select("id").limit(1).execute()
            )
        except Exception:
            pass  # Non-fatal — heartbeat already written above

        await asyncio.sleep(interval)
