"""Tests for utils.row and utils.display_name.

Both exist because of a live bug, and both are pure, so they are worth pinning.
Dependency-free: the two functions are lifted straight out of the source, since
importing utils drags in google.api_core for a helper that does not need it.

    python3 tests/test_utils.py
"""
import ast
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_SRC = open(os.path.join(os.path.dirname(__file__), "..", "utils.py")).read()
_tree = ast.parse(_SRC)
_keep = [
    n for n in _tree.body
    if (isinstance(n, ast.FunctionDef) and n.name in {"row", "display_name"})
    or (isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "_NAME_LINE")
]
_g = {"re": re, "__name__": "pure"}
exec(compile(ast.Module(body=_keep, type_ignores=[]), "utils.py", "exec"), _g)
row = _g["row"]
display_name = _g["display_name"]

failures = []


def check(label, actual, expected):
    if actual != expected:
        failures.append(f"{label}\n     expected: {expected!r}\n     actual:   {actual!r}")
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

print()
if failures:
    print(f"✗ {len(failures)} failure(s):\n")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("✓ all utils tests passed")
