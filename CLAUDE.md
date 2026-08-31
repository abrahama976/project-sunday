# Project Sunday

Personal AI assistant. Read [README.md](./README.md) for architecture and
[ROADMAP.md](./ROADMAP.md) for current state before starting work. Keep both
accurate rather than adding a third planning document.

## Standing constraints

These are project rules, not preferences. Do not relax them without asking:

- **`budget_gate.py` is the only path to an LLM call.** Everything routes
  through `pick_model` / `check_and_increment`. The free tier is ~250
  requests/day and every code path shares it.
- **No autonomous writes.** Write-tier tools queue to `action_queue` and wait
  for approval in the UI. `auto` tier is for reads plus task create/update.
- **Email is drafted, never sent.** Calendar events are suggested, never booked
  unattended.
- **Soft-delete only** for tasks and messages.
- **UI is dark-mode, mobile-first, 390px baseline.**

## The brain is a self-modifying system prompt

`brain_directives` rows are injected into every system prompt. When touching
`executors/brain_ops.py`, `summariser.py`, or the schema, preserve all four:

1. `brain_learn` stays approve-tier.
2. `source` may only be `user` or `inferred`. **Never** derive a directive from
   `web_fetch`, `web_search`, email bodies, or any tool output — that turns
   fetched content into persistent instructions. Enforced in the executor and
   by a `CHECK` constraint.
3. Count and character caps stay enforced — this text rides every request.
4. Near-duplicates supersede rather than stack.

Facts go to `update_profile`; rules go to `brain_learn`. Keep them separate.

## Conventions

- Python: `supabase-py` uses **snake_case** (`maybe_single()`, not
  `maybeSingle()`). A JS-name call is a silent `AttributeError` at runtime.
- Wrap blocking Supabase calls in `asyncio.to_thread`.
- Background tasks get an `add_done_callback` that escalates to `sys.exit(1)`
  so `launchd` recycles the worker. Do not add a bare `create_task`.
- Scheduler jobs store **local** hours against their `timezone` column;
  `scheduler.py` honours it. Do not pre-convert to UTC — it drifts under DST.
- New tools need three edits: `tools/registry.py` (declaration),
  `config.py` `TOOL_TIER_MAP` (tier), `main.py` `_make_registry` (executor).
  A missing tier falls through to `approve`, which is safe but implicit.

## Tests

```bash
python3 apps/worker/tests/test_brain.py   # pure logic, no dependencies
./supabase/tests/run.sh                   # migrations against throwaway PG
cd apps/web && npx tsc --noEmit && npx eslint src/
```

## Note on `apps/web`

Next.js version there is ahead of most training data — see `apps/web/AGENTS.md`.
Auth guard lives in `src/proxy.ts`, which is the current convention, not the
deprecated `middleware.ts`.
