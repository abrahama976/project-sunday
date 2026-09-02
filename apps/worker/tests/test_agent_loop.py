"""End-to-end tests for the agentic loop.

These drive the REAL run_agent_loop against a scripted model and a fake tool
registry, so the control flow, the agent_turns telemetry and the
function_call/function_response threading are all exercised for real. Only two
things are faked: the model (route_turn) and the database.

Requires google-genai (for types.Content) and supabase, because the loop builds
genuine Content objects — testing that with hand-rolled stubs would prove
nothing about whether Gemini would accept them.

    pip install google-genai supabase python-dotenv google-api-core
    SUPABASE_URL=x SUPABASE_SERVICE_ROLE_KEY=x GEMINI_API_KEY=x \
        python3 tests/test_agent_loop.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test")
os.environ.setdefault("GEMINI_API_KEY", "test")

try:
    from google.genai import types  # noqa: E402
    import agent_loop  # noqa: E402
    from agent_loop import (  # noqa: E402
        run_agent_loop, truncate_for_context, best_partial_answer,
    )
except ModuleNotFoundError as e:
    print(f"SKIP: {e.name} is not installed.\n"
          "These tests build real google.genai Content objects, so they need the\n"
          "worker's own dependencies:\n"
          "    pip install -r apps/worker/requirements.txt\n"
          "(test_brain.py has no such requirement and runs anywhere.)")
    sys.exit(0)

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


# ── Fakes ──────────────────────────────────────────────────────────────────

class FakeTable:
    def __init__(self, sink): self._sink = sink; self._row = None
    def insert(self, row): self._row = row; return self
    def execute(self): self._sink.append(self._row); return type("R", (), {"data": [self._row]})()


class FakeClient:
    """Captures agent_turns rows the loop writes."""
    def __init__(self): self.rows = []
    def table(self, name): return FakeTable(self.rows)


def model_says_text(text, model="gemini-flash"):
    return {"status": "ok", "content": types.Content(role="model", parts=[types.Part(text=text)]),
            "text": text, "function_call": None, "model_used": model}


def model_calls(tool, args, text="", model="gemini-flash"):
    """A model turn carrying a function call, as the real SDK would shape it."""
    parts = []
    if text:
        parts.append(types.Part(text=text))
    parts.append(types.Part(function_call=types.FunctionCall(name=tool, args=args)))
    return {"status": "ok", "content": types.Content(role="model", parts=parts),
            "text": text, "function_call": {"name": tool, "args": args}, "model_used": model}


class Harness:
    """Runs the real loop against a scripted sequence of model responses."""

    def __init__(self, script, registry=None, tiers=None, max_iters=None, degraded=None):
        self.script = list(script)
        self.registry = registry or {}
        self.tiers = tiers or {}
        self.max_iters = max_iters
        self.degraded = degraded
        self.client = FakeClient()
        self.replies = []
        self.queued = []
        self.calls_made = 0
        self.contents_seen = []
        self.degraded_calls = []

    async def _route_turn(self, client, contents, user_id, key):
        self.calls_made += 1
        # Snapshot how many turns the model is being shown each round.
        self.contents_seen.append(len(contents))
        if not self.script:
            raise AssertionError("loop asked for more model calls than the script provides")
        return self.script.pop(0)

    async def _on_write_tier(self, tool, args):
        self.queued.append((tool, args))
        return f"I've prepared {tool} for your approval — open More → Approvals to review it."

    async def _insert_reply(self, text, model_used):
        self.replies.append((text, model_used))

    async def _degraded_reply(self, provider):
        self.degraded_calls.append(provider)
        return self.degraded

    def run(self):
        orig_route, orig_tiers, orig_max = (
            agent_loop.route_turn, agent_loop.TOOL_TIER_MAP, agent_loop.MAX_TOOL_ITERS)
        agent_loop.route_turn = self._route_turn
        agent_loop.TOOL_TIER_MAP = self.tiers
        if self.max_iters is not None:
            agent_loop.MAX_TOOL_ITERS = self.max_iters
        try:
            return asyncio.run(run_agent_loop(
                self.client,
                message="test message",
                history=[],
                user_id="11111111-1111-1111-1111-111111111111",
                message_id="22222222-2222-2222-2222-222222222222",
                gemini_api_key="test",
                registry=self.registry,
                on_write_tier=self._on_write_tier,
                insert_reply=self._insert_reply,
                degraded_reply=self._degraded_reply if self.degraded is not None else None,
            ))
        finally:
            agent_loop.route_turn, agent_loop.TOOL_TIER_MAP, agent_loop.MAX_TOOL_ITERS = (
                orig_route, orig_tiers, orig_max)

    # Telemetry helpers
    def types_logged(self): return [r["type"] for r in self.client.rows]
    def rows_of(self, t): return [r for r in self.client.rows if r["type"] == t]
    def reply_text(self): return self.replies[0][0] if self.replies else None


async def _tool(value):
    return value


print("\n── truncation (design §5) ─────────────────────────────")

check("calendar_query is never truncated",
      truncate_for_context("calendar_query", "x" * 5000), "x" * 5000)
check("task_list is never truncated",
      truncate_for_context("task_list", "x" * 5000), "x" * 5000)
check_true("web_fetch keeps 1000 chars",
           truncate_for_context("web_fetch", "x" * 5000).startswith("x" * 1000))
check_true("unknown tools default to 800",
           truncate_for_context("web_search", "x" * 5000).startswith("x" * 800)
           and not truncate_for_context("web_search", "x" * 5000).startswith("x" * 801))
check_true("short results pass through untouched",
           truncate_for_context("web_search", "brief") == "brief")

# gmail_read_body keeps the ask at the top and the signature at the bottom.
body = "ASK" + ("m" * 3000) + "SIGNOFF"
gm = truncate_for_context("gmail_read_body", body)
check_true("gmail_read_body keeps the head", gm.startswith("ASK"))
check_true("gmail_read_body keeps the tail", gm.endswith("SIGNOFF"))
check_true("gmail_read_body drops the middle", len(gm) < len(body))

print("\n── partial answers (design §4) ────────────────────────")

check("a tool result wins over a thought",
      best_partial_answer("real result", "just thinking"), "real result")
check("a thought is used only when no result exists",
      best_partial_answer(None, "just thinking"), "just thinking")
check("neither yields the budget fallback",
      best_partial_answer(None, None),
      "I couldn't complete that request with the current budget.")
check("an empty result does not beat a thought",
      best_partial_answer("   ", "thought"), "thought")

print("\n── one round, no tool ─────────────────────────────────")

h = Harness([model_says_text("Sydney is sunny.")])
check("returns True", h.run(), True)
check("costs exactly one model call", h.calls_made, 1)
check("replies with the answer", h.reply_text(), "Sydney is sunny.")
check("logs thought then final", h.types_logged(), ["thought", "final"])
check_true("final carries the model", h.rows_of("final")[0]["model"] == "gemini-flash")

print("\n── multi-step chain — the whole point ─────────────────")

h = Harness(
    script=[
        model_calls("calendar_query", {"date": "tomorrow"}, text="Checking your calendar."),
        model_calls("travel_directions", {"to": "Office"}, text="Now the travel time."),
        model_says_text("Standup at 9. Leave by 8:30."),
    ],
    registry={
        "calendar_query": lambda **k: _tool("09:00 Standup at Office"),
        "travel_directions": lambda **k: _tool("28 minutes by train"),
    },
    tiers={"calendar_query": "auto", "travel_directions": "auto"},
)
check("chain completes", h.run(), True)
check("three model calls", h.calls_made, 3)
check("final answer reaches the user", h.reply_text(), "Standup at 9. Leave by 8:30.")
check("both tools ran in order",
      [r["tool_name"] for r in h.rows_of("tool_call")],
      ["calendar_query", "travel_directions"])
check("results were captured",
      [r["result"] for r in h.rows_of("tool_result")],
      ["09:00 Standup at Office", "28 minutes by train"])
check("telemetry covers every step", h.types_logged(),
      ["thought", "tool_call", "tool_result",
       "thought", "tool_call", "tool_result",
       "thought", "final"])
# Each round adds the model's call turn plus the function_response turn.
check("context grows by two turns per round", h.contents_seen, [1, 3, 5])
check_true("only the final answer is sent to chat", len(h.replies) == 1)

print("\n── write-tier halts the loop (design §6) ──────────────")

h = Harness(
    script=[
        model_calls("gmail_draft", {"to": "a@b.com", "subject": "Hi"}, text="I'll draft that."),
        model_says_text("should never be reached"),
    ],
    tiers={"gmail_draft": "approve"},
)
check("returns True", h.run(), True)
check("stops after one model call", h.calls_made, 1)
check("the action was queued", h.queued, [("gmail_draft", {"to": "a@b.com", "subject": "Hi"})])
check("user is told to approve", h.reply_text(),
      "I've prepared gmail_draft for your approval — open More → Approvals to review it.")
check_true("halt is recorded",
           h.rows_of("loop_break")[0]["error"] == "write-tier-halt")
check_true("the executor was never run inline",
           not any(r["type"] == "tool_result" for r in h.client.rows))

print("\n── no-progress detector (design §2) ───────────────────")

h = Harness(
    script=[
        model_calls("task_list", {"status": "open"}),
        model_calls("task_list", {"status": "open"}),   # identical — no progress
        model_says_text("unreachable"),
    ],
    registry={"task_list": lambda **k: _tool("2 open tasks")},
    tiers={"task_list": "auto"},
)
h.run()
check("breaks on the repeat", h.calls_made, 2)
check_true("logged as no-progress",
           h.rows_of("loop_break")[0]["error"] == "no-progress")
check("falls back to the last real result", h.reply_text(), "2 open tasks")

# Same tool with DIFFERENT args is legitimate progress, not a loop.
h = Harness(
    script=[
        model_calls("task_list", {"status": "open"}),
        model_calls("task_list", {"status": "done"}),
        model_says_text("Two open, five done."),
    ],
    registry={"task_list": lambda **k: _tool("some tasks")},
    tiers={"task_list": "auto"},
)
h.run()
check("different args are not a loop", h.calls_made, 3)
check("answer completes normally", h.reply_text(), "Two open, five done.")

print("\n── iteration cap (design §2) ──────────────────────────")

h = Harness(
    script=[model_calls("task_list", {"n": i}) for i in range(10)],
    registry={"task_list": lambda **k: _tool("still working")},
    tiers={"task_list": "auto"},
    max_iters=3,
)
h.run()
check("stops at the cap", h.calls_made, 3)
check_true("logged as cap-hit", h.rows_of("loop_break")[0]["error"] == "cap-hit")
check("user gets the best partial answer", h.reply_text(), "still working")
check_true("[capped] is recorded in telemetry",
           h.rows_of("final")[0]["result"].endswith("[capped]"))
check_true("[capped] is NOT shown to the user", "[capped]" not in h.reply_text())

print("\n── budget exhaustion mid-loop (design §4) ─────────────")

h = Harness(
    script=[
        model_calls("calendar_query", {"date": "today"}),
        {"status": "exhausted"},
    ],
    registry={"calendar_query": lambda **k: _tool("Dentist at 3pm")},
    tiers={"calendar_query": "auto"},
)
h.run()
check("keeps what it gathered", h.reply_text(),
      "Dentist at 3pm [Running in local/low-power mode: budget exhausted]")
check_true("logged as budget-exhausted",
           h.rows_of("loop_break")[0]["error"] == "budget-exhausted")

# Degrading to a chat-only provider ends the loop for the same reason.
h = Harness(
    script=[{"status": "degraded", "provider": "ollama"}],
    tiers={},
)
h.run()
check_true("degrade is recorded with the provider",
           h.rows_of("loop_break")[0]["error"] == "degraded-ollama")
check_true("degraded reply carries the low-power suffix",
           h.reply_text().endswith("[Running in local/low-power mode: budget exhausted]"))

# Degrading on round ONE must not cost the user an answer. Before the fallback
# existed the loop apologised here, where the old single-shot router would have
# returned a real Ollama reply — a straight regression for anyone who ran out
# of Gemini budget.
h = Harness(
    script=[{"status": "degraded", "provider": "ollama"}],
    tiers={},
    degraded={"type": "text", "content": "[Ollama] Sydney is sunny.", "model_used": "ollama"},
)
h.run()
check("a first-round degrade still answers properly",
      h.reply_text(), "[Ollama] Sydney is sunny.")
check("the chat-only provider was actually asked", h.degraded_calls, ["ollama"])
check("and the reply is attributed to it", h.replies[0][1], "ollama")
check_true("no apology suffix when a real answer came back",
           "budget exhausted" not in h.reply_text())

# Mid-loop is the opposite call: evidence already gathered beats restarting
# without it, so the partial answer wins and the fallback is not consulted.
h = Harness(
    script=[
        model_calls("calendar_query", {"date": "today"}),
        {"status": "degraded", "provider": "ollama"},
    ],
    registry={"calendar_query": lambda **k: _tool("Dentist at 3pm")},
    tiers={"calendar_query": "auto"},
    degraded={"type": "text", "content": "[Ollama] I don't know.", "model_used": "ollama"},
)
h.run()
check("mid-loop keeps the evidence instead", h.reply_text(),
      "Dentist at 3pm [Running in local/low-power mode: budget exhausted]")
check("the fallback is not consulted mid-loop", h.degraded_calls, [])

print("\n── hallucinated tool recovers (design §9) ─────────────")

h = Harness(
    script=[
        model_calls("summon_unicorn", {"colour": "pink"}),
        model_says_text("Sorry — I'll use a real tool. Two tasks open."),
    ],
    registry={"task_list": lambda **k: _tool("2 open")},
    tiers={"summon_unicorn": "auto"},
)
check("the turn survives an unknown tool", h.run(), True)
check("the model got another round", h.calls_made, 2)
check_true("the error was fed back, not raised",
           "unknown tool" in (h.rows_of("tool_result")[0]["error"] or ""))
check("and it answered", h.reply_text(), "Sorry — I'll use a real tool. Two tasks open.")

print("\n── a failing tool is an observation, not a crash ──────")

async def _boom(**kwargs):
    raise RuntimeError("Google Calendar returned 401")

h = Harness(
    script=[
        model_calls("calendar_query", {"date": "today"}),
        model_says_text("I couldn't reach your calendar — the token looks expired."),
    ],
    registry={"calendar_query": _boom},
    tiers={"calendar_query": "auto"},
)
check("the turn survives", h.run(), True)
check_true("the failure is recorded",
           "401" in (h.rows_of("tool_result")[0]["error"] or ""))
check("the model explained it to the user", h.reply_text(),
      "I couldn't reach your calendar — the token looks expired.")

print("\n── telemetry integrity ────────────────────────────────")

h = Harness(
    script=[
        model_calls("task_list", {"status": "open"}, text="Looking."),
        model_says_text("Two open."),
    ],
    registry={"task_list": lambda **k: _tool("2 open")},
    tiers={"task_list": "auto"},
)
h.run()
run_ids = {r["run_id"] for r in h.client.rows}
check_true("every row shares one run_id", len(run_ids) == 1)
check_true("every row carries the message_id",
           all(r["message_id"] == "22222222-2222-2222-2222-222222222222" for r in h.client.rows))
check_true("step_index advances across rounds",
           [r["step_index"] for r in h.client.rows] == [0, 0, 0, 1, 1])
check_true("tool latency is measured",
           isinstance(h.rows_of("tool_result")[0]["latency_ms"], int))
check_true("every row's type is schema-legal",
           set(h.types_logged()) <= {"thought", "tool_call", "tool_result", "final", "loop_break"})

# Telemetry must never be able to take down the answer.
class ExplodingClient(FakeClient):
    def table(self, name):
        raise RuntimeError("database is on fire")

h = Harness([model_says_text("Answered anyway.")])
h.client = ExplodingClient()
check("a dead telemetry table does not lose the reply", h.run(), True)
check("the user still gets their answer", h.reply_text(), "Answered anyway.")

print()
if failures:
    print(f"✗ {len(failures)} failure(s):\n")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print(f"✓ all agent loop tests passed")
