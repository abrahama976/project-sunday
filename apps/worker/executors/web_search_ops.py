import asyncio
from ddgs import DDGS

async def web_search(query: str, max_results: int = 3) -> str:
    """Perform a web search using duckduckgo-search and return a clean text summary."""
    try:
        def do_search():
            return list(DDGS().text(query, max_results=max_results))
            
        results = await asyncio.to_thread(do_search)
        
        if not results:
            return f"No search results found for query: '{query}'."
            
        output = [f"Search Results for '{query}':\n"]
        for idx, res in enumerate(results, start=1):
            title = res.get("title", "No Title")
            url = res.get("href", "No URL")
            snippet = res.get("body", "No description available.")
            output.append(f"{idx}. {title}\n   URL: {url}\n   Snippet: {snippet}\n")
            
        return "\n".join(output)
    except Exception as e:
        return f"Error performing web search for '{query}': {e}"
