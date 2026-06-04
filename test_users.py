import asyncio
from apps.worker.main import get_client
async def run():
    c = get_client()
    users = await asyncio.to_thread(lambda: c.auth.admin.list_users())
    print("USERS:", users)
    if users:
        print("FIRST USER ID:", users[0].id)
asyncio.run(run())
