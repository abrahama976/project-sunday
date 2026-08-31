"""Unit tests for the pure logic in the learning brain.

Deliberately dependency-free: these import the parsing/similarity helpers
without pulling in supabase or the google SDK, so they run anywhere.

    python3 tests/test_brain.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ── Load the helpers without importing the modules' heavy dependencies ──────
# brain_ops imports supabase; summariser imports google.genai. We only want the
# pure functions, so pull them out of the source directly.


def _load_pure(path: str, names: list[str], extra_globals: dict | None = None):
    src = open(os.path.join(os.path.dirname(__file__), "..", path)).read()
    tree_globals = {"re": re, "__name__": "pure"}
    tree_globals.update(extra_globals or {})
    import ast
    tree = ast.parse(src)
    keep = [
        n for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.Assign))
        and (getattr(n, "name", None) in names
             or (isinstance(n, ast.Assign)
                 and any(getattr(t, "id", None) in names for t in n.targets)))
    ]
    exec(compile(ast.Module(body=keep, type_ignores=[]), path, "exec"), tree_globals)
    return tree_globals


brain = _load_pure(
    "executors/brain_ops.py",
    ["_tokens", "_stem", "_similarity", "_STOPWORDS", "_SUPERSEDE_THRESHOLD", "render_directives", "VALID_SCOPES"],
    {"BRAIN_MAX_CHARS": 6000},
)
summ = _load_pure(
    "summariser.py",
    ["_split_sections", "_parse_rules"],
    {"BRAIN_MAX_PROPOSALS_PER_RUN": 2, "VALID_SCOPES": {
        "general", "code", "calendar", "email", "tasks", "news", "health", "travel"}},
)

_similarity = brain["_similarity"]
_render = brain["render_directives"]
_split = summ["_split_sections"]
_parse = summ["_parse_rules"]
THRESHOLD = brain["_SUPERSEDE_THRESHOLD"]

failures = []


def check(label, actual, expected):
    if actual != expected:
        failures.append(f"{label}\n     expected: {expected!r}\n     actual:   {actual!r}")
    else:
        print(f"  ok  {label}")


def check_true(label, cond, detail=""):
    if not cond:
        failures.append(f"{label} {detail}")
    else:
        print(f"  ok  {label}")


print("\n── similarity / supersede ─────────────────────────────")

# Restatements of the same rule must clear the threshold, or the brain
# accumulates near-duplicate rules that argue with each other.
check_true(
    "restatement is detected as a duplicate",
    _similarity("Keep answers short.", "Keep your answers shorter.") >= THRESHOLD,
    f"(got {_similarity('Keep answers short.', 'Keep your answers shorter.'):.2f})",
)

check_true(
    "same rule, different phrasing",
    _similarity("Show code before the explanation.", "Show the code before explanation.") >= THRESHOLD,
    f"(got {_similarity('Show code before the explanation.', 'Show the code before explanation.'):.2f})",
)

# Genuinely different rules must NOT collapse into one another — a false
# supersede silently deletes a rule the user asked for.
check_true(
    "unrelated rules stay separate",
    _similarity("Keep answers short.", "Never send email without asking.") < THRESHOLD,
    f"(got {_similarity('Keep answers short.', 'Never send email without asking.'):.2f})",
)

check_true(
    "same topic, opposite intent, still separate rules",
    _similarity("Always include code comments.", "Draft emails in a formal tone.") < THRESHOLD,
    f"(got {_similarity('Always include code comments.', 'Draft emails in a formal tone.'):.2f})",
)

check_true("empty directive scores zero", _similarity("", "anything") == 0.0)
check_true("stopword-only directive scores zero", _similarity("the a to for", "of in on at") == 0.0)

print("\n── prompt rendering ───────────────────────────────────")

check("no directives renders nothing", _render([]), "")

rendered = _render([
    {"directive": "Keep replies under three sentences.", "scope": "general", "weight": 5},
    {"directive": "Show code first.", "scope": "code", "weight": 4},
    {"directive": "Never draft on weekends.", "scope": "email", "weight": 3},
])
check_true("general scope is rendered first",
           rendered.index("[general]") < rendered.index("[code]"))
check_true("all directives present", all(
    d in rendered for d in
    ["Keep replies under three sentences.", "Show code first.", "Never draft on weekends."]))
check_true("has closing delimiter", rendered.strip().endswith("--- END DIRECTIVES ---"))

# The char cap is a last line of defence for rows written outside the executor
# (a manual dashboard edit). Verify it actually truncates.
brain["BRAIN_MAX_CHARS"] = 50
capped = _render([
    {"directive": "A" * 40, "scope": "general", "weight": 5},
    {"directive": "B" * 40, "scope": "general", "weight": 4},
])
check_true("char cap truncates the set", "B" * 40 not in capped)
brain["BRAIN_MAX_CHARS"] = 6000

print("\n── summariser section splitting ───────────────────────")

facts, rules = _split(
    "FACTS:\n- Lives in Sydney.\n\nRULES:\n[code] Show code first.\n"
)
check("facts extracted", facts, "- Lives in Sydney.")
check("rules extracted", rules, "[code] Show code first.")

# A malformed response must degrade to facts-only, never lose both halves.
facts2, rules2 = _split("FACTS:\n- Lives in Sydney.\n")
check("missing RULES header keeps facts", facts2, "- Lives in Sydney.")
check("missing RULES header yields no rules", rules2, "")

check("empty input is handled", _split(""), ("", ""))

print("\n── rule parsing ───────────────────────────────────────")

check("well-formed rules parse",
      _parse("[code] Show code first.\n[general] Be brief."),
      [("code", "Show code first."), ("general", "Be brief.")])

check("NOTHING_NEW yields nothing", _parse("NOTHING_NEW"), [])
check("empty yields nothing", _parse(""), [])

check("bullet prefixes are stripped",
      _parse("- [code] Show code first."),
      [("code", "Show code first.")])

check("unknown scope falls back to general",
      _parse("[banana] Do the thing."),
      [("general", "Do the thing.")])

check("unscoped lines are dropped", _parse("Just some prose with no scope."), [])

# The per-run cap stops one chatty conversation flooding the approvals queue.
check("proposals are capped per run",
      len(_parse("[code] One.\n[code] Two.\n[code] Three.\n[code] Four.")),
      2)

check("over-long directives are rejected",
      _parse(f"[code] {'x' * 600}"), [])

print()
if failures:
    print(f"✗ {len(failures)} failure(s):\n")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("✓ all brain tests passed")
