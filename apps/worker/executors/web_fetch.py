import re
from html.parser import HTMLParser

import httpx

_MAX_CHARS = 8000
_USER_AGENT = "Mozilla/5.0 (compatible; ProjectSunday/1.0)"


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self._parts.append(text)

    def get_text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self._parts)).strip()


def _strip_html(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return parser.get_text()


async def web_fetch(url: str) -> str:
    if not url.startswith("https://"):
        raise ValueError("Only HTTPS URLs are allowed")

    async with httpx.AsyncClient(
        timeout=15.0,
        headers={"User-Agent": _USER_AGENT},
        follow_redirects=True,
    ) as client:
        response = await client.get(url)
        response.raise_for_status()

    text = _strip_html(response.text)
    if len(text) > _MAX_CHARS:
        text = text[:_MAX_CHARS] + "\n…[truncated]"
    return text or "(No readable text found)"
