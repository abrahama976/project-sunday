import asyncio
from supabase import Client

async def run_heartbeat(client: Client, interval: int = 60):
    while True:
        try:
            client.table("mac_heartbeat").upsert(
                {"id": 1, "last_seen": "now()", "status": "online"}
            ).execute()
        except Exception as e:
            print(f"[heartbeat] error: {e}")
        await asyncio.sleep(interval)
