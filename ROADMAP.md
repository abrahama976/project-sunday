# Roadmap

The single live plan. Supersedes `phase_3_architecture.md`, `README_NEW.md` and
the Antigravity handover, all of which disagreed with each other and with the
code. If something here is wrong, fix it here rather than starting a new
document.

Last updated: **2026-09-01**

---

## Where things stand

| Component | State | Note |
|---|---|---|
| Supabase | Up | Migrations through `20260831000000` |
| `apps/web` | Deployed | Today, Chat, Tasks, Approvals, Schedule, Health, Profile, Settings, Inventory |
| `apps/worker` | **Not running** | Silent since 2026-07-01. Needs re-auth, then start |
| Google OAuth | **In production** | 7-day expiry retired. Tokens minted in Testing still need one re-auth |
| LLM router | Built | Flash 2.5 → Lite → 2.0 → 2.0-Lite → Groq → Ollama, budget-gated |
| Learning brain | Built | `brain_directives`, approve-tier, capped, superseding |
| Watchdog | **Armed & proven** | Topic set; ntfy returned 200 on a live alert |
| **Agentic loop** | Built | `agent_loop.py`, 5 rounds max, budget-gated per round |
| `agent_turns` | Written | thought / tool_call / tool_result / final / loop_break |
| Agent trace UI | Built | `/traces` — run list, steps in order, termination reason |

---

## Phase 0 — Revive · *in progress*

- [x] Repair the learning loop — `maybe_single()`, summariser call signature
- [x] `mac_heartbeat.status` migration (written by the worker, never migrated)
- [x] Scheduler timezones — `meal_checkin` was firing at 23:00 and 05:00 Sydney,
      `cold_storage_archive` on Sunday afternoons. (`daily_brief` was already
      correct — pinned, not fixed.)
- [x] `schedule_reminder` explicit in `TOOL_TIER_MAP`
- [x] Dead-man's watchdog outside the Mac
- [x] The learning brain
- [x] Collapse the documentation
- [x] Runbook for the two manual steps — [docs/runbook.md](./docs/runbook.md)
- [x] **Google consent screen published to Production** — status reads
      *In production*, External, 1/100 user cap. The 7-day refresh-token expiry
      is retired for tokens minted from here on.
- [x] Migrations applied and the watchdog armed — verified against the live
      database, not the ledger: `pg_net` 0.20.0 and `pg_cron` 1.6.4 installed,
      the cron job active on `*/5 * * * *`, and ntfy returning **200** for a
      real alert.
- [ ] **Re-authorise Google**, then start the worker. Publishing does not heal
      tokens minted under Testing — `rm token_*.json`, run `main.py`, approve
      both consent screens. Expect a "Sunday is back" push once it comes up.
- [ ] Watch one full scheduler cycle

## Phase 1 — The agentic loop (Sprint 3.T1) · *done*

Tools can chain now. *"What's on tomorrow and when do I need to leave?"* runs
`calendar_query` then `travel_directions` and answers once.

- [x] `agent_loop.py` — think → act → observe, `MAX_TOOL_ITERS = 5`
- [x] Tool results fed back as `function_response`; history as `types.Content`
- [x] `agent_turns` gets its writers
- [x] Per-tool truncation before re-injection (§5); full output still persisted
- [x] Write-tier call queues the action and halts the loop (§6)
- [x] No-progress detector — identical tool + args twice running breaks out
- [x] Unknown tool is fed back as an observation, never raised (§9)

**Three deviations from the design doc, all deliberate:**

1. **§6 lists `task_create`/`task_update` as write-tier**; `config.py` has them
   `auto`, and that is correct. The loop runs them inline and keeps going.
2. **§1 has a separate routing call decide whether to enter loop mode.** Doing
   that literally spends two model calls on every message that needs a tool.
   The loop's first round *is* the routing call, so a message needing no tool
   still costs exactly one — same observable behaviour, budget not doubled.
3. **Degrading to Groq/Ollama before any tool has run** hands the question to
   that provider for a real answer, rather than the design's partial answer
   plus low-power suffix. Returning an apology where the old single-shot
   router gave a real reply would have been a straight regression. Mid-loop
   the design's rule stands: gathered evidence beats starting over.

## Phase 2 — Make it legible (Sprint 3.T4) · *done*

Sunday chains up to five steps, and the chat transcript could not tell you what
it did or why it stopped — only the `final` row reaches chat. **More → Traces**
now reads `agent_turns` back, which is what it was indexed on `run_id` for.

- [x] Trace view grouped by `run_id`, reachable from More
- [x] Per run: steps in order, tool args, truncated results, termination reason

The run list reads `final` rows — every loop exit writes exactly one, so that
*is* the list of runs. Termination reasons come from the `loop_break` row's
`error`, rendered as English rather than the slug the worker stores; a run with
no `loop_break` row simply ran to an answer.

`supabase/tests/seed_trace_demo.sql` seeds one synthetic run for looking at the
page before the worker is back writing real ones. It writes to the real project
and carries its own teardown.

## Phase 3 — Prune · *next*

The feature surface is wider than the usage, and every unused job is something
that can break quietly while nobody is watching — which is what produced the
twelve-week gap. Decide each on evidence after a fortnight of real use:

- **Inventory** — a page and a tier entry, in no roadmap and no handover.
- **Meal check-ins / health logging** — has been firing at 11pm and 5am, so
  there is no honest signal on whether it works. Now fixed; judge it after use.
- **News fetch** — six feeds twice daily plus a `web_search` fallback, against
  the same 250/day budget as conversation. Measure its share first.
- **The two-user constraint** — shared budgets, `get_active_users` loops and
  deferred context isolation all serve a second user. If that user is
  hypothetical, this is complexity bought against a requirement that does not
  exist, and Sprint 5's isolation work disappears with it.

---

## Deferred

- Streaming responses — complex to reconcile with intermediate loop steps
- Voice input
- Multi-user context isolation (Sprint 5, and see Phase 3 above)
- Per-user ntfy channels — `poll_reminders` currently uses one global topic

---

## Known issues

1. **Google OAuth 7-day expiry.** Top of Phase 0. Manual fix.
2. **Migration drift.** `mac_heartbeat.status` was written by the worker but
   never migrated. Now confirmed: the live column holds `'online'`, not the
   `'offline'` default a newly-created column would carry, so it had been added
   by hand in the dashboard and heartbeat writes were never failing. The
   migration closed the drift for anyone rebuilding from scratch. Prefer
   migrations over dashboard edits — this one cost an afternoon of uncertainty.
3. **Global ntfy topic.** `poll_reminders` pushes to one topic for all users.
4. **The dormancy was 60 days, not twelve weeks.** The last commit is
   2026-06-06 but `mac_heartbeat.last_seen` reads 2026-07-01 — the worker ran
   for three and a half weeks after the code went quiet. Worth remembering when
   reasoning about what "still worked" at the end.
