import re
import asyncio
from supabase import Client
from context.loader import fetch_and_cache_profile

async def update_profile(client: Client, user_id: str, section: str, content: str) -> str:
    res = await asyncio.to_thread(lambda: client.table("user_profile").select("content").eq("user_id", user_id).maybeSingle().execute())
    
    if not res.data:
        text = ""
    else:
        text = res.data.get("content", "")
        
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
