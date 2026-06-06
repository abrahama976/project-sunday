# Sprint 3 — Agentic Loop Design
**Status:** Draft — Awaiting Review  
**Hard constraints:** Zero recurring cost · Worker on Mac · 250 RPD Gemini free tier shared by 2 users · No autonomous writes · budget_gate.py is the ONLY LLM call path

## 1. State Machine
The core loop operates on a `think → act → observe` pattern:
1. **Route (Entry)**: The incoming message is evaluated. If it requires multi-step reasoning or tool usage, it enters loop mode. If it's a simple greeting or factual query, it returns a direct text reply.
2. **Think**: The model reasons about the current state, budget, and tools available, emitting a `thought` and a potential `tool_call`.
3. **Act**: The worker executes the requested tool. If the tool is a read operation, it executes inline. If it's a write operation, it queues the action and halts the loop.
4. **Observe**: The result of the `tool_call` is fed back into the model's context for the next round.

```text
       [User Message]
             │
         ┌───▼───┐
         │ route │──(direct text)─▶ [Reply]
         └───┬───┘
             │ (tool needed)
             ▼
      ┌─────────────┐
   ┌─▶│   Think     │
   │  └──────┬──────┘
   │         │
   │  ┌──────▼──────┐
   │  │    Act      │──(write tool)─▶ [Queue Action & End]
   │  └──────┬──────┘
   │         │
   │  ┌──────▼──────┐
   └──│  Observe    │
      └─────────────┘
```
The transition from a direct text reply vs. loop mode is triggered by `route()`. If `route()` returns `{"type": "tool_call", ...}`, `handle_message` enters loop mode. If it returns `{"type": "text", ...}`, it skips the loop and replies directly.

## 2. Loop Parameters
- **MAX_TOOL_ITERS**: `5` (to be defined as a configurable variable, not hardcoded inline).
- **No-progress detector**: The loop will break immediately if the model calls the exact same tool with identical arguments (exact dictionary equality `==` on `args`) as the immediately preceding round. When triggered, this event is logged to the `agent_turns` table with `type="loop_break"`.
- **On cap hit**: If `MAX_TOOL_ITERS` is reached without a final answer, the loop returns the best partial answer assembled from the results so far. The internal note `"[capped]"` is appended to the `agent_turns` final row, but it is **not** shown to the user.

## 3. State Persistence (agent_turns)
The `agent_turns` table tracks the granular steps of the loop. All steps within a single turn share a newly generated UUID for `run_id`. The `message_id` maps back to the user message that initiated the loop.

Data is inserted according to the exact `type`:
- `type="thought"`: The model's reasoning text, captured before tool dispatch.
- `type="tool_call"`: Records `tool_name`, `args`, `step_index`, `run_id`, and `message_id`.
- `type="tool_result"`: Records the execution output (`result` or `error`), `latency_ms`, and `est_tokens`.
- `type="final"`: The final reply text, `model` used, and total turn latency. This is the **only** content that is mirrored to the `messages` table for the user to see.
- `type="loop_break"`: The reason for early termination (e.g., "no-progress" or "cap-hit").

## 4. Budget Awareness
- **Pre-flight checks**: `budget_gate.py` is invoked **before each round** in the loop, not just once per turn.
- **Budget exhaustion handling**: If the budget is exhausted mid-loop:
  1. The loop stops immediately.
  2. The worker assembles the "best partial answer" from `tool_results` gathered so far.
  3. A final message is inserted, ending with the exact string: `" [Running in local/low-power mode: budget exhausted]"`.
  4. A `type="final"` row is written to `agent_turns`, and the turn ends.
- **Best partial answer assembly**: Uses the text from the last `tool_result` that completed successfully. If no tool completed, it falls back to the model's last `thought` text. If neither exists, it defaults to: `"I couldn't complete that request with the current budget."`

## 5. Context Management
Tool results must be truncated before re-injection into the LLM context to prevent window overflow. The full, untruncated result is always persisted to `agent_turns.result`.

**Truncation Policies**:
- `calendar_query` / `task_list`: **No truncation** (output is inherently structured and bounded).
- `gmail_read_body`: Keep the first 800 chars and the last 200 chars (preserves the core message ask and sender signature).
- `news_fetch` / `web_fetch`: Keep the first 1000 chars.
- All other tools: Cap at the first 800 chars.

**Total Context Ceiling**:
The sliding window for the model prompt will contain the user profile (prepended) plus the last 15 conversation messages. When approaching the context limit during the loop, the **oldest `tool_result` entries** within the active loop are evicted first, before touching the core conversation history.

## 6. Write-Tier Safety
Write-tier tools include: `calendar_create`, `calendar_update`, `gmail_draft`, `task_create`, `task_update`, `update_profile`, and `schedule_reminder`.

When the loop encounters a write-tier tool call:
1. **Log Thought**: A `type="thought"` row is written to `agent_turns` with the model's narrated plan.
2. **Queue Action**: A new row is inserted into `action_queue` containing a **complete standalone payload**. This payload must contain every concrete argument the executor requires (e.g., `summary`, `start`, `end`, `location`, `description` for `calendar_create`), fully resolved at queue time, relying on zero loop context.
3. **Notify User**: An approve-tier message is inserted into `messages`: `"I've prepared [action] for your approval. Check the Approvals tab."`
4. **Halt Loop**: The loop ENDS immediately. No further iterations occur after a write-tier action is queued.

**Post-execution confirmation**: Once the user approves the queued action, `execute_action()` (outside the loop) handles running the executor and formatting the result via the `_action_result_message()` template.

## 7. Recovery from Crash (Message-Claim Reaper)
**Current Gap**: Mid-loop crashes leave a message permanently `claimed_by='mac'` with no user response.
**Sprint 3 T0 Design**:
1. **Migration**: `ALTER TABLE messages ADD COLUMN claimed_at TIMESTAMPTZ;`
2. **Claiming**: Update `claimed_at = NOW()` alongside `claimed_by` when picking up a message.
3. **Reaper Coroutine**: Runs every 5 minutes (similar to `reap_stale_processing`).
   - Query: `claimed_by IS NOT NULL AND claimed_at < NOW() - INTERVAL '10 minutes'`
   - Condition: No `assistant` message exists with `created_at > claimed_at` for that `user_id`.
   - Reset: Set `claimed_by = NULL` and `claimed_at = NULL`.
   - Log: `[msg-reaper] Reset {n} stale claim(s)`.
4. **Re-processing**: The main poll loop will naturally pick up the unclaimed message again.

**Safety Guarantee**: Since write-tier actions are queued to `action_queue` rather than executed inline, re-processing a crashed loop only repeats safe read operations. Any approve-tier actions re-queued during the retry are protected by `idempotency_key` deduplication.

## 8. Low-Power Mode Signaling
When the primary Gemini model is unavailable, the fallback Ollama state must be surfaced to the user UI.
1. `budget_gate.py` / `route()` returns a response containing a `model_used` field.
2. If `model_used == "ollama"`, `handle_message` will set `metadata->>'low_power' = 'true'` on the `messages` table insert.
3. The frontend (Next.js) checks this specific metadata field when rendering the message bubble and conditionally displays the pre-styled low-power indicator.

## 9. Risk Analysis

| Risk | Severity | Mitigation |
| :--- | :--- | :--- |
| **Hallucinated / unregistered tool name** | High | Before dispatch, validate tool name against registry. If unknown, write type='tool_result' to agent_turns with error='unknown tool X' and feed back as a function_response observation. Model self-corrects next round. Never raise — a validation error must be recoverable. |
| **Loop hitting `MAX_TOOL_ITERS` on valid complex request** | Low | Returns best partial answer and safely exits. No runaway loops. |
| **Budget exhausted before round 1** | High | Fails gracefully via `budget_gate.py` rejecting the initial loop entry. |
| **Worker crash mid-loop** | High | Mitigated by §7 (Message-Claim Reaper). Message is cleanly reset and retried. |
| **Duplicate write on crash/retry** | Critical | Mitigated by Sprint 2 `idempotency_key` injection on `action_queue` items. |
| **Context window exceeds model limit mid-loop** | Medium | Mitigated by §5 structured truncation and oldest-first `tool_result` eviction policies. |
| **Gemini returns malformed `function_call` JSON** | High | Loop logs parsing error in `tool_result`, model attempts regeneration in next round. |
| **Google OAuth refresh token expiry (7-day Testing TTL)** | High | Explicitly deferred. Worker logs auth failure; manual re-auth required currently. |
| **`poll_approved` task dies silently** | Medium | The main event loop continues, but approvals stall. Deferred to future resilience sweep. |

## 10. Out of Scope (Sprint 3)
The following features are explicitly deferred:
- **Trace view UI (S3.T4)**: Deferred until the backend loop logic is entirely stable and proven.
- **`poll_approved` `gemini_api_key` dead-arg cleanup**: Earmarked for the first official Sprint 3 commit.
- **Background task escalation to `sys.exit(1)`**: Deferred resilience improvement for silently dying tasks.
- **Approval card renderers (S2-6)**: Custom UI for the 9 raw-JSON action types is postponed.
- **Multi-user context isolation**: System remains tuned for 2 shared-budget users. Full isolation deferred to Sprint 5.
- **Streaming responses**: Deferred due to complexity with intermediate loop steps.
- **Voice input**: Outside the scope of core reasoning loop.
