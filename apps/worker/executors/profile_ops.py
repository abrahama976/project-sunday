import re
import asyncio
from supabase import Client
from context.loader import fetch_and_cache_profile

async def update_profile(client: Client, section: str, content: str) -> str:
    res = await asyncio.to_thread(lambda: client.table("user_profile").select("user_id, content").limit(1).execute())
    
    if not res.data:
        try:
            users = await asyncio.to_thread(lambda: client.auth.admin.list_users())
            if not users:
                return "Error: No users found in the system. Cannot attach profile."
            user_id = users[0].id
        except Exception as e:
            return f"Error fetching users: {e}"
        text = ""
    else:
        row = res.data[0]
        text = row.get("content", "")
        user_id = row.get("user_id")
        
    section_pattern = re.compile(rf"^(#+)\s+{re.escape(section)}\s*$", re.MULTILINE | re.IGNORECASE)
    match = section_pattern.search(text)
    
    if match:
        insert_pos = match.end()
        text = text[:insert_pos] + f"\n- {content}" + text[insert_pos:]
    else:
        text = text.rstrip() + f"\n\n## {section}\n- {content}\n"
        
    await asyncio.to_thread(lambda: client.table("user_profile").upsert({"user_id": user_id, "content": text}).execute())
    await asyncio.to_thread(lambda: fetch_and_cache_profile(client))
    
    return f"Profile updated: added to section '{section}'"
