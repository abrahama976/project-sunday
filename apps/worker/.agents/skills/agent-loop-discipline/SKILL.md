---
name: agent-loop-discipline
description: "Use when changing the worker's agent loop, tool registry, model routing, memory caps or scheduled autonomy — anything in apps/worker that spends a model request, adds a tool, grows the system prompt, or keeps the worker running unattended. Triggers: agent_loop.py, route_turn, budget_gate, pick_model, tools/registry.py, TOOL_TIER_MAP, MAX_TOOL_ITERS, brain_directives, summariser, scheduler, heartbeat, watchdog, context/loader.py, truncate_for_context."
metadata:
  author: project-sunday
  version: "1.0.0"
---

# Agent-loop discipline

The general-purpose advice about agents is written for someone with an API budget
and no approval model. This project has neither. Every rule below is the same
advice after it has been priced against the two constraints that actually bind
here:

- **250 Gemini requests/day, shared by two users.** `budget_gate.py` is the only
  path to a model, and `route_turn` runs the gate *every round*, so a five-round
  turn costs five.
- **No autonomous writes.** Anything that changes the world stops at
  `action_queue` and waits for a human tap.

Where the popular advice conflicts with those, the constraint wins. That is the
whole content of this skill.

## 1. Tool declarations are a per-request tax, not a one-off

The most under-priced thing in this codebase is `tools/registry.py`. All ~24
declarations with their full descriptions are rebuilt by
`build_gemini_tools()` and sent on **every round of every turn** — up to five
times per message, 250 messages a day.

The "Code Mode" argument (one tool that *writes a script* instead of N narrow
tools, because a service's MCP surface can cost a million tokens of manuals) is
correct in general and **wrong to adopt here**, for one specific reason: the
tier system works because each tool name the model emits is individually
visible at the moment it is called. `TOOL_TIER_MAP` maps a name to `auto` /
`approve` / `hold`; a generated script is a single opaque call whose contents
the approval queue cannot classify, let alone preview. Adopting Code Mode would
mean either executing unclassified code or refusing everything.

So take the diagnosis, not the cure:

- **A new tool has to earn its description length.** Every sentence rides every
  request. The long, hard-won descriptions on `trip_plan`, `calendar_update` and
  `brain_learn` are the exception: they prevent a specific, expensive mistake
  (planning a trip leg-by-leg, inventing an event id, learning from a fetched
  page). A tool added for convenience does not get that treatment.
- **Never add a tool the model can compose from existing ones.** "What's on
  tomorrow and when must I leave" is `calendar_query` then `leave_by` — two
  calls, both visible, both costed. A `morning_brief_all` tool would hide them
  behind one name and one prompt paragraph.
- **Measure before arguing about it.** A description edit is a prompt change:
  re-read the tool's row in `TOOL_TIER_MAP` in the same commit, because a
  renamed tool with no tier silently falls through to `approve`.

## 2. Verification must not cost a second model call

"Have a second agent check the first agent's work" is the single most repeated
piece of advice in the material behind this skill. It is also, here, a 50%
capacity cut: a critic pass on every turn means 125 usable messages instead of
250, and the critic is drawn from the same free tier.

This project verifies deterministically instead, and that is the design, not a
gap to close:

| Claim to be checked | What checks it, at zero requests |
|---|---|
| Did the model make progress? | No-progress detector in `agent_loop.py` — identical tool + identical args ends the turn |
| Did it loop forever? | `MAX_TOOL_ITERS` cap, `loop_break` row with `cap-hit` |
| Did a write happen? | It did not: write-tier halts before execution |
| What did it actually do? | `agent_turns`, one row per step, read back in Traces |
| Is the wiring correct? | `tests/test_agent_loop.py`, a scripted fake model against the real loop |

The one place model-level checking *is* affordable is the approval card, and it
already exists: a human reading `action_queue` is a better verifier than a
smaller model, and it costs nothing. When you are tempted to add a critic pass,
implement the check as a deterministic assertion in the loop or as a better
approval preview instead.

Corollary for hooks: the useful hook is the one that runs *before* the spend.
`pick_model` already does this. A post-hoc hook that inspects an answer and
asks another model to grade it is the expensive version of the same thing.

## 3. Memory is curated, not accumulated

"Memory that sticks across sessions" is cheap to demo and expensive to run,
because memory is prompt text and prompt text is paid on every request. The caps
exist for that reason and are load-bearing:

- `BRAIN_MAX_DIRECTIVES = 40`, `BRAIN_MAX_CHARS = 6000`. A rule that is not
  worth 120 characters on all 250 daily requests is not a rule.
- `build_contents` windows `history[-20:]`. That window *is* the compaction
  strategy. Raising it to "remember more" spends tokens on every turn to help a
  rare one.
- `context/loader.py` caches the profile and directives — the database reads,
  never the assembled prompt. Do not add a cache of the prompt string: it
  carries `NOW`, and a cached copy dates the model.

The rule to keep from the agent-memory tools: **supersede, don't stack.** A
restated preference replaces the old row. Two directives that disagree are worse
than one, because the model has to guess which is newer.

## 4. Routing degrades capability, never correctness

The cascade in `budget_gate.pick_model` is the "auto mode" idea from the
multi-model routing tools, with the tiers ordered so that what runs out first is
the most capable model, not the most correct behaviour:

```
Flash 2.5 → Lite → Flash 2.0 → Flash 1.5 → Groq → Ollama → EXHAUSTED
```

Groq and Ollama are **chat-only in this worker**. Degrading to them ends
tool-calling; it does not end the reply, which is the entire point —
`degraded_reply` answers properly rather than apologising with a partial answer
that was never gathered. Two rules follow:

- **Never place a non-tool-calling provider above a tool-calling one** in the
  order. A message that needed a tool would silently stop being able to use one.
- **Never add a provider to the cascade to fix a quality complaint.** Adding a
  provider to a system with a hard request cap buys variance, not capacity. Fix
  the prompt or the tool description, which costs nothing.

## 5. Unattended running is a supervision problem

"Ran for 690 hours straight" describes endurance. Endurance is not the failure
mode here; *silent* running is. The worker's answers to that are already built
and should not be traded away for uptime:

- `scheduler._in_flight` — a job slower than the tick must not start twice.
  Release it in a `finally`, or one raising job never runs again.
- `add_done_callback` → `sys.exit(1)` so `launchd` recycles the process. Do not
  replace it with a bare `create_task`, which is how a worker keeps running and
  keeps doing nothing.
- `heartbeat` + the pg_cron watchdog → ntfy. It ships inert and is armed in
  `docs/runbook.md`.

The 690-hour lesson that *does* transfer: a long run is only safe when each step
is observable afterwards. `agent_turns` is that record. Anything that makes a
step invisible (a model call outside `route_turn`, an insert into `messages`
from inside the loop) removes the supervision the endurance depends on.

## 6. What does not apply here, and why

Recorded so the same ground is not re-covered:

- **Running a huge model locally.** A 2.78T-parameter MoE inferring on one CPU
  in ~8 GB works by keeping almost nothing resident and paging experts from
  disk. It is a real result and it is irrelevant to this worker: the brain is a
  hosted API call, there are no weights here, and importing a local model would
  add a download, a runtime and a thermal problem to a machine whose job is to
  poll Supabase. The *transferable* part — keep the hot path small, page the
  rest from storage — is already the shape of `context/loader.py` plus the
  cold-archive bucket.
- **Smaller/compressed local models as a budget fix.** The reported size and
  quality figures are benchmark-specific. Replacing the primary model on a
  marketing number would trade a known-good tier for an unknown one, and the
  free tier is gated on requests/day, not on tokens, so a smaller model saves
  nothing that is actually scarce.
- **Paid coding-plan subscriptions and free-model routing for the *developer*.**
  Useful for a human editing this repo; irrelevant to the worker's runtime,
  which is a single Gemini key plus optional Groq and Ollama.

## 7. The meta-rule

Solve the problem you have; do not collect tools. Every mechanism in the loop
above exists because something specific broke: the date bug produced `NOW` in
the prompt, seven catch-up jobs produced the OAuth rule, a five-step answer
arriving as five chat messages produced the `final`-row-only rule. A change that
cannot name the failure it prevents is a preference, and preferences here cost
requests.

## Checklist before touching the loop

- [ ] Does this add a model call? Then it spends the 250/day budget — say how
      many requests it costs and where it sits relative to `budget_gate.py`.
- [ ] Does it add a tool? Declaration + `TOOL_TIER_MAP` + `_make_registry` in the
      same commit, description justified, tier explicit.
- [ ] Does it grow the system prompt? Count the characters; this text rides
      every request, including the ones that fail.
- [ ] Does it make any step invisible? If so, it needs an `agent_turns` row.
- [ ] Would a deterministic assertion catch this instead of a model?
- [ ] Can the failure it prevents be named concretely?

See `references/sources.md` for the reviewed sources behind each rule.
