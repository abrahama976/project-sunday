"""Using a web search to ask TfNSW a better question.

The important thing this module does NOT do: produce a coordinate. `ddgs` 9.x
has no geocoding — it returns titles, URLs and snippets, and it reaches them
through Startpage and Google rather than DuckDuckGo directly, so it is both
unstructured and less reliable than the name suggests. Building a route on a
lat/lng scraped out of a search snippet would put untrusted text at the very
bottom of the stack, under every leg of the journey, which is exactly the class
of failure this project keeps paying for.

So the search never resolves anything. It only rewrites the QUERY, and TfNSW —
a transit authority, with structured stops, `isBest` and `matchQuality` — still
does every geocode. The worst a bad search result can do is send TfNSW looking
for a place that does not exist, which fails visibly and safely.

It runs twice, and both times conditionally:

- **Before**, only when the text looks like a venue rather than a place. TfNSW's
  stop_finder is excellent at suburbs and stops and poor at business names:
  "Kogarah" resolves perfectly and must not pay for a search, while "Qudos Bank
  Arena" resolves badly and is worth one. `needs_search` draws that line.
- **After**, when TfNSW found nothing or the plausibility gate rejected
  everything. Here the search is the last thing between an answer and "I could
  not find that".

Everything in this module is pure except `place_hint`, which makes the one call.
"""
import re

# A postcode is the strongest signal a snippet can carry: "Sydney Olympic Park
# NSW 2127" is unambiguous in a way that a bare suburb name is not, and it is
# the format Australian addresses are actually written in.
_SUBURB_POSTCODE = re.compile(
    r"\b([A-Z][A-Za-z'\-]*(?:\s+[A-Z][A-Za-z'\-]*){0,3}),?\s+"
    r"(NSW|New South Wales)\s+(\d{4})\b"
)

# Weaker, but common in venue listings that omit the postcode.
_SUBURB_STATE = re.compile(
    r"\b([A-Z][A-Za-z'\-]*(?:\s+[A-Z][A-Za-z'\-]*){0,3}),\s+(NSW|New South Wales)\b"
)

# Words that mean "this is a thing at a place" rather than "this is a place".
# A venue name reaching stop_finder unaided is the case worth spending a search
# on; a suburb name is not.
#
# Deliberately NOT here: park, gardens, beach, bay, point, hill, heights,
# grove, vale. Sydney names dozens of suburbs with them — Sydney Olympic Park,
# Moore Park, Centennial Park, Bondi Beach, Rose Bay — and stop_finder resolves
# every one of those perfectly. Including them sent real suburbs off to a web
# search for no gain, which the tests caught.
_VENUE_WORDS = frozenset("""
arena stadium mall plaza hospital clinic surgery university
college campus library museum gallery theatre theater cinema hotel
motel pub cafe café restaurant bakery gym wharf
terminal airport tower studio church
temple mosque synagogue racecourse showground
""".split())

# Never worth a search: these resolve well already, or resolve to something
# only the app knows.
_NEVER_SEARCH = frozenset({"home", "work", "here", "school", "uni", "gym"})

# Tokens that mean the text is already an address, which stop_finder handles.
_ADDRESS_RE = re.compile(r"\b\d+[a-z]?\s+[A-Za-z]", re.IGNORECASE)

# The state or a NSW postcode anywhere in the text: enough to say the user has
# already supplied the locality a search would go looking for.
_HAS_LOCALITY = re.compile(r"\b(NSW|New South Wales|2\d{3})\b", re.IGNORECASE)


def needs_search(text: str) -> bool:
    """True when a web search would tell TfNSW something it does not know.

    Deliberately conservative: a false positive costs one search and a little
    latency, but running this on every plain suburb would put scraped text on
    the hot path of a system that currently works, for no gain. "Kogarah",
    "Sans Souci" and "314 Gardeners Rd" all return False.
    """
    cleaned = (text or "").strip()
    if not cleaned:
        return False
    lowered = cleaned.lower()
    if lowered in _NEVER_SEARCH:
        return False
    # An address: a street number and a street name. stop_finder is good at
    # these and a search would only add noise.
    if _ADDRESS_RE.search(cleaned):
        return False
    # Already carries its own locality — nothing left to look up. Tested on the
    # bare state or postcode token rather than the full suburb patterns, which
    # want a comma the user has no reason to type: "Qudos Bank Arena, Sydney
    # Olympic Park NSW" carries its suburb and must not be searched again.
    if _HAS_LOCALITY.search(cleaned):
        return False

    words = [w for w in re.split(r"[\s,]+", lowered) if w]
    if any(w.strip(".'s") in _VENUE_WORDS for w in words):
        return True
    # A possessive is almost always a business: "Nick's", "Harry's".
    if "'" in cleaned:
        return True
    # Four or more words is a description, not a suburb name. Sydney's longest
    # suburb names run to three ("Sydney Olympic Park").
    return len(words) >= 4


def search_query(text: str) -> str:
    """The query to search for. Anchored to NSW so the answer is local."""
    return f"{(text or '').strip()} Sydney NSW address suburb"


def suburb_from_text(blob: str) -> str | None:
    """The first NSW suburb named in some text, or None. Pure.

    Prefers a suburb carrying a postcode, because that pattern is unambiguous;
    falls back to "Something, NSW". Returns the suburb alone — not the whole
    match — because it is about to be appended to the user's own words.
    """
    if not blob:
        return None
    for pattern in (_SUBURB_POSTCODE, _SUBURB_STATE):
        match = pattern.search(blob)
        if match:
            suburb = match.group(1).strip(" ,")
            # A single very short token is noise, not a suburb.
            if len(suburb) >= 3:
                return suburb
    return None


def refine(text: str, blob: str) -> str | None:
    """`text` plus the suburb a search revealed, or None if it revealed none.

    None rather than `text` unchanged is the point: the caller must be able to
    tell "the search added nothing" from "the search suggested this", so it can
    skip a second identical lookup and say honestly which query it used.
    """
    suburb = suburb_from_text(blob)
    if not suburb:
        return None
    original = (text or "").strip()
    if not original:
        return None
    # Already there — nothing gained, and repeating it makes the query worse.
    if suburb.lower() in original.lower():
        return None
    return f"{original}, {suburb} NSW"


async def place_hint(text: str) -> str | None:
    """Search the web and return a refined query, or None. Never raises.

    The only impure function here, and the only one that can be slow. Failure —
    no network, a rate limit, a backend change — is indistinguishable from "the
    search found nothing useful", which is correct: in both cases the caller
    should carry on with what the user actually typed.
    """
    try:
        from executors.web_search_ops import web_search
        blob = await web_search(search_query(text), max_results=3)
    except Exception as exc:                     # noqa: BLE001
        print(f"[trip] place search failed for {text!r}: {exc}")
        return None
    return refine(text, blob or "")
