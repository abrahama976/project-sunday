import asyncio
from supabase import Client

async def run_heartbeat(client: Client, interval: int = 60):
    while True:
        try:
            await asyncio.to_thread(
                lambda: client.table("mac_heartbeat").upsert(
                    {"id": 1, "last_seen": "now()", "status": "online"}
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
