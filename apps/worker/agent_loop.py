"""The agentic loop — think → act → observe.

Before this, the worker routed a message, executed at most one tool, and
stopped. Twenty tools existed and none of them could chain: "what's on tomorrow
and when do I need to leave?" needs calendar_query and then travel_directions,
and that was two questions asked by hand.

Implements docs/sprint_3_design.md. The shape:

    route_special ─(handled)─▶ reply
          │
          ▼
    ┌──────────┐
 ┌─▶│  think   │  route_turn: budget gate + Gemini cascade
 │  └────┬─────┘
 │       │ function_call?  no ──▶ final answer, reply, done
 │       ▼ yes
 │  ┌──────────┐
 │  │   act    │  write-tier ──▶ queue for approval, HALT
 │  └────┬─────┘
 │       ▼
 │  ┌──────────┐
 └──│ observe  │  truncated result fed back as a function_response
    └──────────┘

Every exit writes a `final` row to agent_turns, and only `final` reaches the
user's chat. Intermediate steps are telemetry, not conversation — otherwise a
five-step answer arrives as five chat messages.

Budget note: the loop's first round IS the routing call. Design §1 describes a
separate routing call deciding whether to enter loop mode, but doing that
literally would spend two model calls on every message that turns out to need a
tool. On a 250-request daily budget shared with real conversation, that
doubling is not affordable. A message needing no tool still costs exactly one
call, as it did before.
"""
import asyncio
import json
import time
import uuid

from google.genai import types
from supabase import Client

from config import MAX_TOOL_ITERS, TOOL_TIER_MAP
from router import build_contents, route_special, route_turn

# ── Truncation before re-injection (design §5) ─────────────────────────────
# Full output is always persisted to agent_turns; only what goes back into the
# model context is cut. Tools whose output is inherently bounded and structured
# are left whole — truncating a calendar mid-event is worse than the tokens.
_NO_TRUNCATE = {"calendar_query", "task_list"}
_HEAD_ONLY = {"web_fetch": 1000}
_HEAD_TAIL = {"gmail_read_body": (800, 200)}
_DEFAULT_HEAD = 800


def truncate_for_context(tool_name: str, result: str) -> str:
    """Cut a tool result down to what is worth re-injecting."""
    if result is None:
        return ""
    text = result if isinstance(result, str) else json.dumps(result, default=str)

    if tool_name in _NO_TRUNCATE:
        return text

    if tool_name in _HEAD_TAIL:
        head, tail = _HEAD_TAIL[tool_name]
        if len(text) <= head + tail:
            return text
        # Keep the opening ask and the sign-off; the middle of an email is
        # usually the part you can lose.
        return f"{text[:head]}\n…[{len(text) - head - tail} chars omitted]…\n{text[-tail:]}"

    limit = _HEAD_ONLY.get(tool_name, _DEFAULT_HEAD)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n…[truncated, {len(text)} chars total]"


# ── Telemetry ──────────────────────────────────────────────────────────────

async def log_turn(
    client: Client,
    run_id: str,
    user_id: str,
    message_id: str | None,
    step_index: int,
    turn_type: str,
    *,
    tool_name: str | None = None,
    args: dict | None = None,
    result: str | None = None,
    error: str | None = None,
    model: str | None = None,
    latency_ms: int | None = None,
) -> None:
    """Write one agent_turns row.

    Never raises: telemetry failing must not take down the answer the user is
    waiting on. A dropped trace row is a worse day for debugging, not for them.
    """
    row = {
        "run_id": run_id,
        "user_id": user_id,
        "step_index": step_index,
        "type": turn_type,
    }
    if message_id:
        row["message_id"] = message_id
    if tool_name:
        row["tool_name"] = tool_name
    if args is not None:
        row["args"] = args
    if result is not None:
        # result is TEXT in the schema (see 20260606220000), so anything
        # structured is serialised rather than handed over as a dict.
        row["result"] = result if isinstance(result, str) else json.dumps(result, default=str)
    if error:
        row["error"] = error
    if model:
        row["model"] = model
    if latency_ms is not None:
        row["latency_ms"] = latency_ms

    try:
        await asyncio.to_thread(
            lambda: client.table("agent_turns").insert(row).execute()
        )
    except Exception as e:
        print(f"[loop] telemetry write failed ({turn_type}): {e}", flush=True)


# ── Partial answers ────────────────────────────────────────────────────────

_BUDGET_SUFFIX = " [Running in local/low-power mode: budget exhausted]"
_NO_ANSWER = "I couldn't complete that request with the current budget."


def best_partial_answer(last_result: str | None, last_thought: str | None) -> str:
    """Assemble the best answer available when the loop ends early (design §4).

    Order matters: a completed tool result is evidence, a thought is only
    intent. Falling back to the thought risks reporting a plan as though it
    were an outcome, so it comes second and never replaces a real result.
    """
    if last_result and last_result.strip():
        return last_result.strip()
    if last_thought and last_thought.strip():
        return last_thought.strip()
    return _NO_ANSWER


# ── The loop ───────────────────────────────────────────────────────────────

async def run_agent_loop(
    client: Client,
    *,
    message: str,
    history: list,
    user_id: str,
    message_id: str | None,
    gemini_api_key: str,
    registry: dict,
    on_write_tier,
    insert_reply,
    degraded_reply=None,
) -> bool:
    """Drive think → act → observe until an answer, a write-tier halt, or a limit.

    `registry` maps tool name to an awaitable executor (main.py owns building
    it, so this module stays free of executor imports).
    `on_write_tier(tool, args)` queues an approval and returns the message to
    show the user.
    `insert_reply(text, model_used)` puts the final answer in the chat.
    `degraded_reply(provider)` optionally answers via a chat-only provider when
    the budget degrades before any tool has run; returns a result dict or None.

    Returns True if the turn produced a reply.
    """
    run_id = str(uuid.uuid4())
    contents = build_contents(history, message)

    step = 0
    last_call: tuple | None = None
    last_result: str | None = None
    last_thought: str | None = None
    model_used = "system"
    turn_started = time.monotonic()

    async def _final(text: str, *, note: str = "") -> bool:
        elapsed = int((time.monotonic() - turn_started) * 1000)
        await log_turn(
            client, run_id, user_id, message_id, step, "final",
            result=f"{text}{note}", model=model_used, latency_ms=elapsed,
        )
        # The loop was otherwise silent on the happy path: the last thing in
        # the log was "[router] Attempting generation…", so a finished turn and
        # a hung one looked identical. agent_turns knew; the log did not.
        rounds = step + 1
        print(
            f"[loop] answered in {rounds} round{'s' if rounds != 1 else ''} "
            f"via {model_used} ({elapsed}ms){note}",
            flush=True,
        )
        await insert_reply(text, model_used)
        return True

    while step < MAX_TOOL_ITERS:
        turn = await route_turn(client, contents, user_id, gemini_api_key)
        status = turn.get("status")

        # ── Budget gone, or only non-tool-calling providers left ───────────
        # Groq and Ollama are chat-only in this worker, so "degraded" ends the
        # loop for the same reason "exhausted" does: no further tool step is
        # possible.
        if status in ("exhausted", "degraded"):
            reason = "budget-exhausted" if status == "exhausted" else f"degraded-{turn.get('provider')}"
            await log_turn(
                client, run_id, user_id, message_id, step, "loop_break",
                error=reason, model=model_used,
            )

            # Degrading before anything was gathered is not a failed turn — it
            # is what the cascade exists for. Hand the question to the chat-only
            # provider and let it answer properly, rather than apologising with
            # a partial answer we never had. Mid-loop is different: evidence
            # already collected beats starting over without it.
            if (status == "degraded" and degraded_reply is not None
                    and last_result is None and last_thought is None):
                fallback = await degraded_reply(turn.get("provider"))
                if fallback and fallback.get("content"):
                    model_used = fallback.get("model_used", model_used)
                    return await _final(fallback["content"])

            answer = best_partial_answer(last_result, last_thought)
            return await _final(answer + _BUDGET_SUFFIX)

        if status == "error":
            await log_turn(
                client, run_id, user_id, message_id, step, "loop_break",
                error=turn.get("message", "model error"), model=model_used,
            )
            if last_result or last_thought:
                return await _final(best_partial_answer(last_result, last_thought))
            return await _final(turn.get("message", "Something went wrong."))

        model_used = turn.get("model_used", model_used)
        text = (turn.get("text") or "").strip()
        function_call = turn.get("function_call")

        if text:
            last_thought = text
            await log_turn(
                client, run_id, user_id, message_id, step, "thought",
                result=text, model=model_used,
            )

        # ── No tool wanted: this is the answer ─────────────────────────────
        if not function_call:
            return await _final(text or best_partial_answer(last_result, last_thought))

        tool = function_call["name"]
        args = function_call["args"]

        # ── No-progress detector (design §2) ───────────────────────────────
        # Identical tool and identical args two rounds running means the model
        # is not using what it got back. Another round costs budget and returns
        # the same thing.
        if last_call is not None and last_call == (tool, _freeze(args)):
            await log_turn(
                client, run_id, user_id, message_id, step, "loop_break",
                tool_name=tool, args=args, error="no-progress", model=model_used,
            )
            return await _final(best_partial_answer(last_result, last_thought))
        last_call = (tool, _freeze(args))

        tier = TOOL_TIER_MAP.get(tool, "approve")

        # ── Write-tier: queue and halt (design §6) ─────────────────────────
        if tier != "auto":
            await log_turn(
                client, run_id, user_id, message_id, step, "tool_call",
                tool_name=tool, args=args, model=model_used,
            )
            notice = await on_write_tier(tool, args)
            await log_turn(
                client, run_id, user_id, message_id, step, "loop_break",
                tool_name=tool, args=args, error="write-tier-halt", model=model_used,
            )
            return await _final(notice)

        # ── Unknown tool: recoverable, never fatal (design §9) ─────────────
        # A hallucinated name is fed back as an observation so the model can
        # correct itself next round. Raising would lose the whole turn.
        if tool not in registry:
            err = f"unknown tool '{tool}'"
            await log_turn(
                client, run_id, user_id, message_id, step, "tool_result",
                tool_name=tool, args=args, error=err, model=model_used,
            )
            _observe(contents, turn["content"], tool, f"Error: {err}. Use only the declared tools.")
            step += 1
            continue

        # ── Act ────────────────────────────────────────────────────────────
        await log_turn(
            client, run_id, user_id, message_id, step, "tool_call",
            tool_name=tool, args=args, model=model_used,
        )

        started = time.monotonic()
        try:
            raw = await registry[tool](**args)
            result_text = raw if isinstance(raw, str) else json.dumps(raw, default=str)
            error_text = None
        except Exception as e:
            result_text = None
            error_text = f"{type(e).__name__}: {e}"
            print(f"[loop] tool {tool} failed: {error_text}", flush=True)
        latency = int((time.monotonic() - started) * 1000)

        await log_turn(
            client, run_id, user_id, message_id, step, "tool_result",
            tool_name=tool, args=args,
            result=result_text, error=error_text,
            model=model_used, latency_ms=latency,
        )

        # ── Observe ────────────────────────────────────────────────────────
        # A failed tool is still an observation: the model can try another
        # approach rather than the turn dying here.
        if error_text:
            _observe(contents, turn["content"], tool, f"Error: {error_text}")
        else:
            last_result = result_text
            _observe(contents, turn["content"], tool,
                     truncate_for_context(tool, result_text))

        step += 1

    # ── Iteration cap (design §2) ──────────────────────────────────────────
    # "[capped]" is recorded in agent_turns and deliberately not shown — the
    # user gets the best answer available, not an apology about internals.
    await log_turn(
        client, run_id, user_id, message_id, step, "loop_break",
        error="cap-hit", model=model_used,
    )
    return await _final(best_partial_answer(last_result, last_thought), note=" [capped]")


def _freeze(args: dict):
    """Hashable, order-independent view of tool args, for comparing rounds."""
    try:
        return json.dumps(args, sort_keys=True, default=str)
    except Exception:
        return repr(sorted(args.items())) if isinstance(args, dict) else repr(args)


def _observe(contents: list, model_content, tool: str, observation: str) -> None:
    """Append the model's own call and the resulting observation.

    Both halves are required: Gemini rejects a function_response that does not
    follow the function_call it answers, so the model turn is replayed verbatim
    rather than reconstructed.
    """
    contents.append(model_content)
    contents.append(
        types.Content(
            role="user",
            parts=[types.Part.from_function_response(
                name=tool,
                response={"result": observation},
            )],
        )
    )
