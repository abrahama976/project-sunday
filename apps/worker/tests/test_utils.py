"""Tests for utils.row, utils.display_name and utils.resolve_user.

Each exists because of a live bug or a live assumption, so each is worth
pinning. Dependency-free: the functions are lifted straight out of the source,
since importing utils drags in google.api_core for helpers that do not need it.
`asyncio` is stubbed to a to_thread that just calls its argument — resolve_user
makes exactly one outside call and that is it.

    python3 tests/test_utils.py
"""
import ast
import asyncio
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_SRC = open(os.path.join(os.path.dirname(__file__), "..", "utils.py")).read()
_tree = ast.parse(_SRC)
_keep = [
    n for n in _tree.body
    if (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name in {"row", "display_name", "resolve_user"})
    or (isinstance(n, ast.ClassDef) and n.name == "MultipleUsers")
    or (isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "_NAME_LINE")
]


class _Thread:
    """Stands in for asyncio.to_thread — resolve_user's only outside call."""
    @staticmethod
    async def to_thread(fn):
        return fn()


_g = {"re": re, "asyncio": _Thread, "__name__": "pure"}
exec(compile(ast.Module(body=_keep, type_ignores=[]), "utils.py", "exec"), _g)
row = _g["row"]
display_name = _g["display_name"]
resolve_user = _g["resolve_user"]
MultipleUsers = _g["MultipleUsers"]

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


class Res:
    def __init__(self, data):
        self.data = data


PROFILE = (
    "# About Me\n"
    "**Name:** Abraham\n"
    "**Location:** Sydney, Australia (UTC+10, Australia/Sydney)\n"
)


print("\n── row() ─────────────────────────────────────────────")

# maybe_single() returns None itself when nothing matched — not a response
# object with data=None. This is the distinction that crashed calendar_prep.
check("None result is an empty dict", row(None), {})
check("data=None is an empty dict", row(Res(None)), {})
check("a real row passes through", row(Res({"name": "Abraham"})), {"name": "Abraham"})
check("an empty row is an empty dict", row(Res({})), {})


print("\n── display_name() ────────────────────────────────────")

# The live shape: the column is NULL, the name is in the markdown. This is the
# case that produced "## Good morning, None ☀️" every morning.
check("NULL column falls back to the profile body",
      display_name({"name": None, "content": PROFILE}), "Abraham")
check("...and never returns the string 'None'",
      display_name({"name": None, "content": PROFILE}) == "None", False)
check("the column wins when it is set",
      display_name({"name": "Alstone", "content": PROFILE}), "Alstone")
check("an empty-string column is not a name",
      display_name({"name": "   ", "content": PROFILE}), "Abraham")

check("no name anywhere falls back",
      display_name({"name": None, "content": "# About Me\nNo name here.\n"}), "there")
check("an empty profile falls back", display_name({}), "there")
check("a custom fallback is honoured", display_name({}, fallback="friend"), "friend")

# A greeting wants a first name, not a full one.
check("a full name is cut to the first",
      display_name({"name": None, "content": "**Name:** Abraham Alstone\n"}), "Abraham")
check("surrounding whitespace is trimmed",
      display_name({"name": None, "content": "**Name:**    Abraham   \n"}), "Abraham")

# The H1 is "# About Me" — matching it is what made the web app say
# "Hey, About Me." The name line is the only thing worth reading.
check("the H1 heading is not mistaken for the name",
      display_name({"name": None, "content": PROFILE}) == "About", False)

# The name line does not have to be the first line, or the only bold line.
check("the name line is found further down",
      display_name({"name": None, "content": "# About Me\n**Location:** Sydney\n**Name:** Abraham\n"}),
      "Abraham")

print("\n── resolve_user() ────────────────────────────────────")


class FakeClient:
    """Just enough supabase-py to satisfy resolve_user's one query."""

    def __init__(self, profiles):
        self._profiles = profiles

    def table(self, _name):
        return self

    def select(self, _cols):
        return self

    def execute(self):
        return Res(self._profiles)


def resolved(profiles):
    return asyncio.run(resolve_user(FakeClient(profiles)))


def raises(profiles):
    try:
        resolved(profiles)
        return None
    except MultipleUsers as e:
        return str(e)


ONE = [{"user_id": "u-1", "name": None, "content": PROFILE}]

check("the single user resolves", resolved(ONE)["user_id"], "u-1")
check("...with a real name, not the NULL column", resolved(ONE)["name"], "Abraham")
check("...and carries the profile body", resolved(ONE)["content"].startswith("# About Me"), True)

check("the column wins when it is populated",
      resolved([{"user_id": "u-1", "name": "Alstone", "content": PROFILE}])["name"], "Alstone")
check("no name anywhere still resolves the id",
      resolved([{"user_id": "u-1", "name": None, "content": ""}])["name"], "there")

# The guard that replaces the deleted fan-out. Serving only the first of two
# users silently is the failure this exists to prevent.
two = [{"user_id": "u-1", "content": PROFILE}, {"user_id": "u-2", "content": PROFILE}]
check_true("two users raise", raises(two) is not None)
check_true("...and the message says how many", "2 user profiles" in (raises(two) or ""))
check_true("...and names the fix", "fan-out" in (raises(two) or ""))

check_true("zero users raise", raises([]) is not None)
check_true("rows without a user_id do not count",
           raises([{"user_id": None, "content": PROFILE}]) is not None)
check("one real row beside a null one still resolves",
      resolved([{"user_id": None}, {"user_id": "u-1", "content": PROFILE}])["user_id"], "u-1")


print()
if failures:
    print(f"✗ {len(failures)} failure(s):\n")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("✓ all utils tests passed")
