"""The NVIDIA tier: request shape in, Gemini-shaped turn out.

No network. `httpx.AsyncClient` is swapped for a stub, so what is asserted is
exactly the seam where this tier could go wrong: the conversion of the loop's
Gemini Contents into OpenAI messages, the tool declarations going out, and the
reply coming back as a real `types.Content` so `_observe` can still append it to
the history.

The tier is skipped when no key is configured (proven in test_model_cascade),
so this file covers the case where a key IS configured.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test")
os.environ.setdefault("GEMINI_API_KEY", "test")
os.environ.setdefault("NVIDIA_API_KEY", "test-key")

try:
    from google.genai import types  # noqa: E402
    import router  # noqa: E402
    from config import NVIDIA_MODEL  # noqa: E402
except ModuleNotFoundError as e:
    print(f"SKIP: {e.name} is not installed — these tests build real Content objects.")
    sys.exit(0)

failures = []


def check(label, actual, expected):
    if actual != expected:
        failures.append(f"{label}\n     expected: {expected!r}\n     actual:   {actual!r}")
    else:
        print(f"  ok  {label}")


def check_true(label, cond, detail=""):
    if cond:
        print(f"  ok  {label}")
    else:
        failures.append(f"{label} {detail}")
        print(f"  ✗   {label} {detail}")


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.text = "" if status == 200 else "unauthorized"

    def json(self):
        return self._payload


class _StubClient:
    """Stands in for httpx.AsyncClient; records the request it was given."""
    last = {}
    reply = None
    status = 200

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers=None, json=None):
        _StubClient.last = {"url": url, "headers": headers or {}, "json": json or {}}
        return _Resp(_StubClient.reply or {}, _StubClient.status)


router.httpx.AsyncClient = _StubClient


class Ledger:
    def __init__(self):
        self.calls = []

    def rpc(self, name, params):
        self.calls.append((name, params))
        return self

    def execute(self):
        return type("R", (), {"data": 1})()


def contents_with_history():
    return [
        types.Content(role="user", parts=[types.Part(text="what's on tomorrow?")]),
        types.Content(role="model", parts=[types.Part(text="Checking.")]),
        types.Content(role="model", parts=[types.Part(
            function_call=types.FunctionCall(name="calendar_query", args={"days_ahead": 1})
        )]),
        types.Content(role="user", parts=[types.Part.from_function_response(
            name="calendar_query", response={"result": "2 events"}
        )]),
    ]


async def run():
    print("── contents → OpenAI messages ────────────────────────")
    msgs = router._nvidia_messages(contents_with_history())
    check("one message per turn", len(msgs), 4)
    check("roles map model→assistant", [m["role"] for m in msgs],
          ["user", "assistant", "assistant", "tool"])
    check("the plain model turn keeps its text", msgs[1]["content"], "Checking.")
    call = (msgs[2].get("tool_calls") or [{}])[0]
    check("the function_call becomes a tool_call", call.get("function", {}).get("name"),
          "calendar_query")
    check("its arguments are JSON, not a dict", isinstance(call["function"]["arguments"], str), True)
    check("one stable id links call and result",
          (call["id"], msgs[3]["tool_call_id"]), ("call_0", "call_0"))
    check_true("the tool result is JSON text", msgs[3]["content"].startswith("{"), msgs[3]["content"])

    print("\n── a tool call comes back as a Gemini turn ───────────")
    _StubClient.reply = {
        "choices": [{"message": {
            "content": "",
            "tool_calls": [{"id": "x", "type": "function", "function": {
                "name": "calendar_query", "arguments": '{"days_ahead": 1}'}}],
        }}]
    }
    ledger = Ledger()
    turn = await router._nvidia_turn(ledger, contents_with_history(), "user-a")
    check("status", turn["status"], "ok")
    check("model_used is the configured NVIDIA id", turn["model_used"], NVIDIA_MODEL)
    check("the tool name survives", turn["function_call"]["name"], "calendar_query")
    check("the args are parsed, not a string", turn["function_call"]["args"], {"days_ahead": 1})
    check_true("content is a real Content object",
               isinstance(turn["content"], types.Content), type(turn["content"]))
    check("...with the function_call part the loop expects",
          turn["content"].parts[0].function_call.name, "calendar_query")
    check("the ledger was incremented once", len(ledger.calls), 1)
    check("...on the nvidia tier", ledger.calls[0][1]["p_model"], "nvidia")

    sent = _StubClient.last
    check_true("it posts to /chat/completions", sent["url"].endswith("/chat/completions"), sent["url"])
    check_true("with a bearer key", sent["headers"].get("Authorization", "").startswith("Bearer "), "")
    check("the model id is sent", sent["json"]["model"], NVIDIA_MODEL)
    check_true("the system prompt leads", sent["json"]["messages"][0]["role"] == "system", "")
    registry_size = len(router.TOOLS)
    check("every declared tool goes out", len(sent["json"]["tools"]), registry_size)
    check_true("in OpenAI's shape",
               sent["json"]["tools"][0]["function"].get("name") == router.TOOLS[0]["name"], "")

    print("\n── a plain answer ────────────────────────────────────")
    _StubClient.reply = {"choices": [{"message": {"content": "Two things tomorrow."}}]}
    turn = await router._nvidia_turn(Ledger(), contents_with_history(), "user-a")
    check("status", turn["status"], "ok")
    check("no tool call", turn["function_call"], None)
    check("the text is carried", turn["text"], "Two things tomorrow.")

    print("\n── an auth failure degrades, it does not raise ───────")
    _StubClient.status = 401
    _StubClient.reply = {}
    try:
        turn = await router._nvidia_turn(Ledger(), contents_with_history(), "user-a")
    except Exception as e:  # noqa: BLE001 — the point is that this must not happen
        failures.append(f"an HTTP error escaped as {type(e).__name__}: {e}")
        turn = {}
    check("it returns a degraded turn instead", turn.get("status"), "degraded")
    check_true("...naming a provider the loop can use",
               turn.get("provider") in ("groq", "ollama"), turn.get("provider"))

    print("\n── route_turn hands an exhausted Gemini day to NVIDIA ─")
    async def picks_nvidia(client, user_id, allow_flash=True):
        return NVIDIA_MODEL

    original_pick, original_turn = router.pick_model, router._nvidia_turn
    called = {"nvidia": 0}

    async def spy(client, contents, user_id):
        called["nvidia"] += 1
        return {"status": "ok", "content": None, "text": "", "function_call": None,
                "model_used": NVIDIA_MODEL}

    router.pick_model = picks_nvidia
    router._nvidia_turn = spy
    _StubClient.status = 200
    try:
        turn = await router.route_turn(Ledger(), contents_with_history(), "user-a", "key")
    finally:
        router.pick_model, router._nvidia_turn = original_pick, original_turn
    check("the NVIDIA path ran", called["nvidia"], 1)
    check("...and its result is what comes back", turn.get("model_used"), NVIDIA_MODEL)

    print()
    if failures:
        print(f"✗ {len(failures)} failure(s):\n")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("✓ all NVIDIA tier tests passed")


asyncio.run(run())
