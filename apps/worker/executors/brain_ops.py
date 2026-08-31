"""The learning brain — durable behavioural directives.

Directives are injected into the system prompt on every request, so this module
is effectively writing part of Sunday's own instructions. Everything here is
built around keeping that safe and bounded:

  * brain_learn is 'approve' tier (config.py), so nothing lands without a tap.
  * source='tool' is impossible — a directive may only come from something the
    user said, or from the summariser observing the user. Never from fetched
    web pages or tool output, which would make web_fetch a persistent
    prompt-injection vector.
  * The active set is capped in count and characters. Every request carries
    this text against a 250/day budget, so unbounded growth is a real cost.
  * Contradictions supersede rather than stack, so the set stays coherent
    instead of accumulating rules that argue with each other.
"""
import asyncio
import re

from supabase import Client

from config import BRAIN_MAX_DIRECTIVES, BRAIN_MAX_CHARS
from context.loader import fetch_and_cache_directives

VALID_SCOPES = {
    "general", "code", "calendar", "email", "tasks", "news", "health", "travel",
}

# Words that carry no distinguishing weight when comparing two directives.
_STOPWORDS = {
    "a", "an", "the", "to", "for", "of", "in", "on", "at", "and", "or", "but",
    "is", "are", "be", "was", "were", "with", "as", "by", "from", "that",
    "this", "it", "my", "me", "i", "you", "your", "always", "never", "when",
    "if", "do", "not", "please", "should", "would", "use", "using",
}


def _stem(word: str) -> str:
    """Crude suffix stripping, enough to collapse the inflections that show up
    when someone restates a rule: short/shorter, answer/answers, ask/asking.
    Without it 'keep answers short' and 'keep your answers shorter' score as
    different rules and both end up in the prompt."""
    for suffix, min_len in (("ing", 5), ("est", 5), ("ed", 4), ("er", 4), ("ly", 4)):
        if len(word) > min_len and word.endswith(suffix):
            return word[: -len(suffix)]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _tokens(text: str) -> set[str]:
    """Content words of a directive, lowercased and stemmed, for comparison."""
    words = re.findall(r"[a-z0-9']+", text.lower())
    return {_stem(w) for w in words if w not in _STOPWORDS and len(w) > 2}


def _similarity(a: str, b: str) -> float:
    """Jaccard overlap of content words. Cheap, no dependency, good enough to
    catch 'keep answers short' vs 'keep your answers shorter' without needing
    an LLM call to decide whether two rules are the same rule."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


# Above this, a new directive is treated as a restatement of an existing one
# and supersedes it instead of being added alongside.
_SUPERSEDE_THRESHOLD = 0.6


async def _active_directives(client: Client, user_id: str) -> list[dict]:
    res = await asyncio.to_thread(
        lambda: client.table("brain_directives")
        .select("id, directive, scope, weight")
        .eq("user_id", user_id)
        .eq("active", True)
        .order("weight", desc=True)
        .order("created_at", desc=False)
        .execute()
    )
    return res.data or []


async def brain_learn(
    client: Client,
    user_id: str,
    directive: str,
    scope: str = "general",
    weight: int = 3,
    source: str = "user",
    source_message_id: str | None = None,
) -> str:
    """Teach Sunday a durable rule about how to serve this user.

    Returns a human-readable confirmation; raises on invalid input so the
    action_queue row is marked failed and surfaced in chat.
    """
    directive = (directive or "").strip().rstrip(".") + "."
    directive = directive.strip()

    if len(directive) < 4:
        raise ValueError("Directive is empty.")
    if len(directive) > 500:
        raise ValueError(
            f"Directive is {len(directive)} chars; the limit is 500. "
            "Rules should be one sentence — save longer context to the profile."
        )

    if scope not in VALID_SCOPES:
        scope = "general"

    try:
        weight = max(1, min(5, int(weight)))
    except (TypeError, ValueError):
        weight = 3

    # Provenance is a security boundary, not a label. Anything that is not a
    # first-party observation of the user is refused outright.
    if source not in ("user", "inferred"):
        raise ValueError(
            f"Refusing to learn a directive with source={source!r}. "
            "Directives may only originate from the user, never from tool "
            "output or fetched content."
        )

    existing = await _active_directives(client, user_id)

    # Exact repeat — nothing to do. Cheaper to detect here than to let the
    # unique index raise.
    for row in existing:
        if row["directive"].strip().lower() == directive.lower():
            return f"Already known: “{directive}”"

    # Near-duplicate — supersede the closest match rather than stacking a
    # second rule that says almost the same thing.
    superseded_id = None
    superseded_text = None
    best_score = 0.0
    for row in existing:
        score = _similarity(directive, row["directive"])
        if score > best_score:
            best_score, superseded_id, superseded_text = score, row["id"], row["directive"]

    if best_score < _SUPERSEDE_THRESHOLD:
        superseded_id = superseded_text = None

    # Cap enforcement. Only applies when genuinely adding, since a supersede is
    # net-neutral on the count.
    if superseded_id is None:
        if len(existing) >= BRAIN_MAX_DIRECTIVES:
            raise ValueError(
                f"The brain is full ({BRAIN_MAX_DIRECTIVES} active directives). "
                "Retire one in Profile → Brain before adding another."
            )
        projected = sum(len(r["directive"]) for r in existing) + len(directive)
        if projected > BRAIN_MAX_CHARS:
            raise ValueError(
                f"Adding this would push the brain to {projected} characters, "
                f"over the {BRAIN_MAX_CHARS} budget. Retire or shorten a "
                "directive first — every request pays for this text."
            )

    if superseded_id:
        await asyncio.to_thread(
            lambda: client.table("brain_directives")
            .update({"active": False})
            .eq("id", superseded_id)
            .execute()
        )

    payload = {
        "user_id": user_id,
        "directive": directive,
        "scope": scope,
        "weight": weight,
        "source": source,
        "active": True,
    }
    if source_message_id:
        payload["source_message_id"] = source_message_id
    if superseded_id:
        payload["supersedes"] = superseded_id

    await asyncio.to_thread(
        lambda: client.table("brain_directives").insert(payload).execute()
    )

    await fetch_and_cache_directives(client, user_id)

    if superseded_text:
        return f"Learned: “{directive}” — this replaces “{superseded_text}”"
    return f"Learned: “{directive}” (scope: {scope})"


async def brain_forget(client: Client, user_id: str, directive_id: str) -> str:
    """Retire a directive. Soft-delete — the row stays for audit, matching the
    project's no-hard-deletes rule."""
    res = await asyncio.to_thread(
        lambda: client.table("brain_directives")
        .update({"active": False})
        .eq("id", directive_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not res.data:
        return "No matching directive found."
    await fetch_and_cache_directives(client, user_id)
    return f"Retired: “{res.data[0].get('directive', directive_id)}”"


def render_directives(rows: list[dict]) -> str:
    """Render the active set for injection into the system prompt.

    Grouped by scope so the model can see which rules are situational, and
    hard-truncated as a last line of defence in case rows were written by a
    path that skipped the executor (a manual dashboard edit, say).
    """
    if not rows:
        return ""

    by_scope: dict[str, list[str]] = {}
    total = 0
    for row in rows:
        text = (row.get("directive") or "").strip()
        if not text:
            continue
        if total + len(text) > BRAIN_MAX_CHARS:
            break
        total += len(text)
        by_scope.setdefault(row.get("scope") or "general", []).append(text)

    if not by_scope:
        return ""

    out = [
        "--- LEARNED DIRECTIVES ---",
        "Rules this user has taught you. They override your default behaviour.",
        "If two conflict, prefer the more specific scope.",
        "",
    ]
    # 'general' first, then situational scopes alphabetically.
    for scope in ["general"] + sorted(k for k in by_scope if k != "general"):
        if scope not in by_scope:
            continue
        out.append(f"[{scope}]")
        out.extend(f"- {d}" for d in by_scope[scope])
        out.append("")
    out.append("--- END DIRECTIVES ---")
    return "\n".join(out)
