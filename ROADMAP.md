# Roadmap

The single live plan. Supersedes `phase_3_architecture.md`, `README_NEW.md` and
the Antigravity handover, all of which disagreed with each other and with the
code. If something here is wrong, fix it here rather than starting a new
document.

Last updated: **2026-08-28**

---

## Where things stand

| Component | State | Note |
|---|---|---|
| Supabase | Up | Migrations through `20260828150000` |
| `apps/web` | Deployed | Today, Chat, Tasks, Approvals, Schedule, Health, Profile, Settings, Inventory |
| `apps/worker` | **Not running** | Everything below inherits this |
| Google OAuth | **Expired** | Consent screen on External + Testing — tokens die every 7 days |
| LLM router | Built | Flash 2.5 → Lite → 2.0 → 2.0-Lite → Groq → Ollama, budget-gated |
| Learning brain | Built | `brain_directives`, approve-tier, capped, superseding |
| Watchdog | Built | pg_cron → ntfy. Needs a topic set before it does anything |
| **Agentic loop** | **Not built** | Sprint 3.T1. Designed in full, zero lines written |
| `agent_turns` | No writers | Table and indexes exist; the loop will fill them |
| Agent trace UI | Not built | Sprint 3.T4 |

---

## Phase 0 — Revive · *in progress*

- [x] Repair the learning loop — `maybe_single()`, summariser call signature
- [x] `mac_heartbeat.status` migration (written by the worker, never migrated)
- [x] Scheduler timezones — `meal_checkin` was firing at 23:00 and 05:00 Sydney
- [x] `schedule_reminder` explicit in `TOOL_TIER_MAP`
- [x] Dead-man's watchdog outside the Mac
- [x] The learning brain
- [x] Collapse the documentation
- [x] Runbook for the two manual steps — [docs/runbook.md](./docs/runbook.md)
- [ ] **Publish the Google consent screen to Production** — manual, ~20 min.
      The 7-day expiry is tied to *publishing status*, not verification, so no
      verification is needed. Tokens minted in Testing keep their 7-day fate,
      so re-auth afterwards or nothing changes.
- [ ] Apply the four migrations and set `watchdog_config.ntfy_topic`
- [ ] Start the worker and watch one full scheduler cycle

## Phase 1 — The agentic loop (Sprint 3.T1)

The only remaining change that alters what Sunday can *do*. Twenty tools
currently cannot chain: *"what's on tomorrow and when do I need to leave?"*
needs `calendar_query` then `travel_directions`, and today that is two
questions asked by hand.

Implement `docs/sprint_3_design.md` as written — the design holds up.

- [ ] `handle_message` becomes think → act → observe, `MAX_TOOL_ITERS = 5`
- [ ] Tool results fed back as `function_response`; history as `types.Content`
- [ ] `agent_turns` gets its writers
- [ ] Per-tool truncation before re-injection (§5); full output still persisted
- [ ] Write-tier call queues the action and halts the loop (§6)
- [ ] No-progress detector — identical tool + args twice running breaks out

**Amendment to the design doc:** §6 lists `task_create` and `task_update` as
write-tier, but `config.py` has them `auto` and that is the intended
behaviour — the loop executes them inline and keeps iterating rather than
halting for approval.

## Phase 2 — Make it legible (Sprint 3.T4)

Once Sunday chains five steps, the chat transcript alone cannot tell you what
it did or why it stopped. `agent_turns` is already indexed on `run_id` for
exactly this query.

- [ ] Trace view grouped by `run_id`, reachable from More
- [ ] Per run: steps in order, tool args, truncated results, termination reason

## Phase 3 — Prune

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
   never migrated, and a previous commit exists purely to repair drift. Prefer
   migrations over dashboard edits.
3. **Global ntfy topic.** `poll_reminders` pushes to one topic for all users.
