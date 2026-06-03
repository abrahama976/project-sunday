from supabase import Client

_cache: str = ""

def fetch_and_cache_profile(client: Client) -> str:
    """Fetches the profile from Supabase and caches it for synchronous router usage."""
    global _cache
    res = client.table("user_profile").select("content").limit(1).execute()
    if res.data:
        _cache = res.data[0].get("content", "")
    else:
        _cache = ""
    return _cache

def get_profile() -> str:
    return _cache
