"""News feed executor: fetch, score, and store RSS feed items.

Fetches articles from configured RSS feeds, uses Gemini to score
relevance, and stores them in the news_items Supabase table.
"""
import asyncio
import hashlib
from datetime import datetime, timezone
from xml.etree import ElementTree

import httpx
from google import genai
from google.genai import types
from supabase import Client

from config import GEMINI_MODEL

# Default RSS feeds — configurable via scheduled_jobs config
DEFAULT_FEEDS = [
    {"name": "Hacker News",           "url": "https://hnrss.org/frontpage", "category": "tech"},
    {"name": "TechCrunch",            "url": "https://techcrunch.com/feed/", "category": "startup"},
    {"name": "ABC News AU",           "url": "https://www.abc.net.au/news/feed/51120/rss.xml", "category": "local"},
    {"name": "Sydney Morning Herald", "url": "https://www.smh.com.au/rss/feed.xml", "category": "local"},
    {"name": "Entrepreneur",          "url": "https://feeds.feedburner.com/entrepreneur/latest", "category": "startup"},
    {"name": "The Guardian AU",       "url": "https://www.theguardian.com/australia-news/rss", "category": "local"},
]


async def _fetch_feed(url: str, timeout: float = 15.0) -> list[dict]:
    """Fetch and parse an RSS feed, returning a list of article dicts."""
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.get(url, headers={
            "User-Agent": "ProjectSunday/1.0 (personal-ai; +https://github.com)",
        })
        resp.raise_for_status()

    items = []
    try:
        root = ElementTree.fromstring(resp.text)
        # Handle both RSS 2.0 and Atom feeds
        ns = {"atom": "http://www.w3.org/2005/Atom"}

        # RSS 2.0
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub_date = (item.findtext("pubDate") or "").strip()
            description = (item.findtext("description") or "").strip()
            if title:
                items.append({
                    "title": title[:500],
                    "url": link,
                    "pub_date": pub_date,
                    "description": description[:1000],
                })

        # Atom
        if not items:
            for entry in root.findall(".//atom:entry", ns):
                title = (entry.findtext("atom:title", namespaces=ns) or "").strip()
                link_el = entry.find("atom:link", ns)
                link = link_el.get("href", "") if link_el is not None else ""
                pub_date = (entry.findtext("atom:published", namespaces=ns) or "").strip()
                summary = (entry.findtext("atom:summary", namespaces=ns) or "").strip()
                if title:
                    items.append({
                        "title": title[:500],
                        "url": link,
                        "pub_date": pub_date,
                        "description": summary[:1000],
                    })
    except ElementTree.ParseError:
        pass

    return items[:20]  # Cap per feed


async def _score_articles(
    articles: list[dict],
    gemini_api_key: str,
) -> list[dict]:
    """Use Gemini to score article relevance for the user.
    
    Returns articles with added 'relevance' (0.0-1.0) and 'summary' fields.
    """
    if not articles:
        return []

    titles = "\n".join(f"- [{i}] {a['title']}" for i, a in enumerate(articles))
    prompt = f"""Score the following news headlines for relevance to a tech-savvy
professional in Sydney, Australia who is interested in:
- Software engineering, AI/ML, startups
- Australian markets, property, finance
- Local Sydney/NSW news that affects daily life
- Science and technology breakthroughs

For each article, return a JSON array with objects:
{{"index": <number>, "score": <0.0 to 1.0>, "summary": "<one-sentence summary>"}}

Only include articles scoring >= 0.3. Headlines:
{titles}

Return ONLY the JSON array, nothing else."""

    try:
        client = genai.Client(api_key=gemini_api_key)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
            config=types.GenerateContentConfig(
                max_output_tokens=2048,
                temperature=0.2,
            ),
        )

        text = "".join(
            p.text for p in response.candidates[0].content.parts
            if hasattr(p, "text") and p.text
        ).strip()

        # Parse JSON from response (handle markdown code blocks)
        import json
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        scored = json.loads(text)

        for item in scored:
            idx = item.get("index", -1)
            if 0 <= idx < len(articles):
                articles[idx]["relevance"] = min(1.0, max(0.0, float(item.get("score", 0))))
                articles[idx]["summary"] = item.get("summary", "")

    except Exception as e:
        print(f"[news] scoring error: {e}")
        # Default all to 0.5 if scoring fails
        for a in articles:
            a.setdefault("relevance", 0.5)
            a.setdefault("summary", "")

    return articles


async def news_fetch_and_store(
    client: Client,
    gemini_api_key: str,
    feeds: list[dict] | None = None,
) -> str:
    """Fetch RSS feeds, score articles, and store in Supabase.
    
    This is the main function called by the scheduler.
    """
    feeds = feeds or DEFAULT_FEEDS
    all_articles: list[dict] = []

    for feed in feeds:
        try:
            items = await _fetch_feed(feed["url"])
            for item in items:
                item["source"] = feed["name"]
                item["category"] = feed.get("category", "tech")
            all_articles.extend(items)
            print(f"[news] fetched {len(items)} items from {feed['name']}")
        except Exception as e:
            print(f"[news] failed to fetch {feed['name']}: {e}")

    if not all_articles:
        return "No articles fetched from any feed."

    # Deduplicate by URL hash
    seen = set()
    unique = []
    for a in all_articles:
        key = hashlib.md5((a.get("url") or a["title"]).encode()).hexdigest()
        if key not in seen:
            seen.add(key)
            unique.append(a)
    all_articles = unique

    # Score with Gemini
    scored = await _score_articles(all_articles, gemini_api_key)

    # Filter to relevant articles (score >= 0.3)
    relevant = [a for a in scored if a.get("relevance", 0) >= 0.3]

    # Store in Supabase
    stored = 0
    for article in relevant:
        try:
            published_at = None
            if article.get("pub_date"):
                try:
                    from email.utils import parsedate_to_datetime
                    published_at = parsedate_to_datetime(article["pub_date"]).isoformat()
                except Exception:
                    pass

            client.table("news_items").upsert({
                "title": article["title"],
                "source": article.get("source", ""),
                "url": article.get("url", ""),
                "summary": article.get("summary", ""),
                "relevance": article.get("relevance", 0.5),
                "category": article.get("category", "tech"),
                "published_at": published_at,
                "surfaced": False,
            }, on_conflict="url").execute()
            stored += 1
        except Exception as e:
            print(f"[news] store error: {e}")

    result = f"Fetched {len(all_articles)} articles from {len(feeds)} feeds, stored {stored} relevant items."
    print(f"[news] {result}")
    return result
