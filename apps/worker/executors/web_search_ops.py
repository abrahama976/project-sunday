"""Web search — Tavily primary, DuckDuckGo fallback.
Preserves existing function signature: web_search(query, max_results) -> str
All callers continue to work without changes.
"""
import asyncio
from config import TAVILY_API_KEY

async def web_search(query: str, max_results: int = 3) -> str:
    """Search the web. Returns formatted string of results.
    Uses Tavily if TAVILY_API_KEY is set, otherwise DuckDuckGo.
    """
    results = []
    if TAVILY_API_KEY:
        results = await _tavily_search(query, max_results)
    if not results:
        results = await _ddgs_search(query, max_results)
    if not results:
        return f"No search results found for query: '{query}'."
    output = [f"Search Results for '{query}':\n"]
    for idx, r in enumerate(results, start=1):
        output.append(
            f"{idx}. {r['title']}\n"
            f"   URL: {r['url']}\n"
            f"   Snippet: {r['content']}\n"
        )
    return "\n".join(output)

async def _tavily_search(query: str, max_results: int) -> list[dict]:
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=TAVILY_API_KEY)
        resp = await asyncio.to_thread(
            lambda: client.search(query, max_results=max_results, search_depth="basic")
        )
        return [
            {"title": r.get("title", ""), "url": r.get("url", ""), "content": r.get("content", "")}
            for r in resp.get("results", [])
        ]
    except Exception as exc:
        print(f"[search] Tavily error: {exc} — falling back to DuckDuckGo")
        return []

async def _ddgs_search(query: str, max_results: int) -> list[dict]:
    try:
        from ddgs import DDGS
        results = await asyncio.to_thread(
            lambda: list(DDGS().text(query, max_results=max_results))
        )
        return [
            {"title": r.get("title", ""), "url": r.get("href", ""), "content": r.get("body", "")}
            for r in results
        ]
    except Exception as exc:
        print(f"[search] DuckDuckGo error: {exc}")
        return []
