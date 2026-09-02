# Roadmap

The single live plan. Supersedes `phase_3_architecture.md`, `README_NEW.md` and
the Antigravity handover, all of which disagreed with each other and with the
code. If something here is wrong, fix it here rather than starting a new
document.

Last updated: **2026-09-02**

---

## Where things stand

| Component | State | Note |
|---|---|---|
| Supabase | Up | Migrations through `20260902120000` (`travel_alerts` applied directly) |
| `apps/web` | Deployed | Today, Chat, Tasks, Approvals, Schedule, Health, Profile, Traces, Settings |
| `apps/worker` | Running | Heartbeat `online`; jobs firing. Needs a `git pull` to pick up Phase 4c |
| Google OAuth | **In production** | Re-authorised 2026-09-02 via a Desktop-app client; all services report authorised |
| LLM router | Built | Flash 2.5 → Lite → 2.0 → 2.0-Lite → Groq → Ollama, budget-gated |
| Learning brain | Built | `brain_directives`, approve-tier, capped, superseding |
| Watchdog | **Armed & proven** | Topic set; ntfy returned 200 on a live alert |
| **Agentic loop** | Built | `agent_loop.py`, 5 rounds max, budget-gated per round |
| `agent_turns` | Written | thought / tool_call / tool_result / final / loop_break |
| Agent trace UI | Built | `/traces` — run list, steps in order, termination reason |
| **Travel** | Built, unproven | TfNSW journeys + OpenRouteService driving. Needs an ORS key and one live Sydney trip |

---

## Phase 0 — Revive · *in progress*

- [x] Repair the learning loop — `maybe_single()`, summariser call signature
- [x] `mac_heartbeat.status` migration (written by the worker, never migrated)
- [x] Scheduler timezones — `meal_checkin`'s hours were being read as UTC, and
      `cold_storage_archive` ran on Sunday afternoons. (`daily_brief` was already
      correct — pinned, not fixed.) Note the live table shows `meal_checkin`
      with `last_executed_at` NULL while every other job has a value, so the
      earlier claim that it *was* firing at 23:00 and 05:00 looks wrong: it
      appears never to have fired at all.
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
- [x] **`git pull` on the Mac** — done 2026-09-01, fast-forward
      `a5f8ad9..b3d1167`.

      An earlier revision of this line said the checkout "predates #23". Wrong
      by one: it was *at* `a5f8ad9`, which is #23 — what it lacked was #24 and
      #25. The evidence only ever supported that narrower claim. `agent_turns`
      empty proves the loop had never run (#24); the `✅ web_search completed.`
      reply shape is the branch #24 deleted. `brain_directives` empty proves
      nothing about the code version at all — a directive has simply never been
      approved.
- [x] **Re-authorise Google** — done 2026-09-02. The first attempt failed
      with `redirect_uri_mismatch`: the OAuth client had been created as a *Web
      application*, and `run_local_server` needs a **Desktop app** client. A new
      Desktop client fixed it and the worker now reports all services
      authorised.
- [ ] Set `NTFY_TOPIC` in `apps/worker/.env`, and start Ollama
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

## Phase 3 — Prune · *done*

The feature surface was wider than the usage, and every unused path is something
that can break quietly while nobody is watching — which is what produced the
dormancy. Decided on evidence read from the live database on 2026-09-01, not on
taste.

**Cut:**

| What | Evidence | What went |
|---|---|---|
| The two-user constraint | `auth.users` = **1** | Four `get_active_users()` fan-out loops in `jobs.py`, and the `send_daily_brief_for_all_users` wrapper |
| Inventory | **0 rows**, ever | The page, the More entry, the approvals label, and a `TOOL_TIER_MAP` entry for a tool that never existed |
| `news_fetch` | decided without measuring — see below | `executors/news_ops.py`, the job handler, the `news_items` reads in both briefs, and `morning_briefing`'s four regional `web_search` calls |

**Kept:** `meal_checkin` and `morning_briefing` — both have `last_executed_at`
NULL and have never fired, but they stay by choice. Every table stays too,
including `inventory` and `news_items`; this was a code-and-UI prune, and the
only migration disables the orphaned `news_fetch` job row.

**The fan-out has a guard, not just a deletion.** `utils.resolve_user` raises
`MultipleUsers` if a second `user_profile` row ever appears. Deleting the loops
without it would mean a second user silently gets nothing — no brief, no
calendar prep, no nudges — with nothing in the log to say why. It also fixed a
greeting: `get_active_users()` returns `user_profile.name`, which is NULL, so
the old code fell back to the email prefix and greeted the user as their login.

**`news_fetch` was cut without measurement, deliberately.** `user_llm_ledger`
records `(user_id, ledger_date, model, request_count)` and has no caller
dimension, so its share of the budget was never knowable. What was visible: 158
requests all-time, busiest day **33** against a cap of 250 — the budget pressure
that motivated the item does not appear in the data. If the question ever
matters, the answer is one `source` column on the ledger and one argument
threaded through `check_and_increment`.

**Still open, found while pruning:** `meal_checkin` upserts a
`meal_checkin_retry` row into `scheduled_jobs` that has no registered handler,
so the scheduler logs "no handler for job" whenever it matches. Left alone
rather than silently disabled — the row is a symptom, and `meal_checkin` is
staying, so the fix is a decision about what that retry should do.

---

## Phase 4 — Travel · *built, unproven*

*"Suggest better routes than Maps alone, using public transport to travel faster
and cut waiting."* Four sub-phases; all code has landed on `main`.

**4a — TfNSW.** `trip_plan` and `transit_departures` against the Transport for
NSW Open Data trip planner. Real-time where the feed has it:
`departureTimeEstimated` is the live figure and `departureTimePlanned` the
timetable, and an answer says which one it used rather than presenting a
timetable as fact.

**4b — Ranking.** Journeys sort on **arrive, then wait, then changes, then
duration**. That order is the feature: the stated goal was less time standing on
a platform, which is not the same as the shortest total trip. An alternative is
only mentioned when its saving covers its cost — `_ALT_MAX_LATER_MIN = 15`.

**4c — Leave-by and the push.** `leave_by` plans backwards from an arrival
time; `travel_watch` runs every 5 minutes and sends one ntfy push when it is
time to move. `TRAVEL_BUFFER_MINUTES = 5`, the user's own figure.

**Google Maps was removed, not deferred.** The Directions API returned
`REQUEST_DENIED` on every call: it requires a billing account, which this
project will not have. **OpenRouteService** replaced it for driving — key-only,
no card, 2000 directions/day, and it returns 403 at the cap rather than a bill.
This was diagnosed entirely from the Phase 2 trace view, which is the first time
that page paid for itself.

**Origin resolution.** `utils.resolve_origin` prefers a live GPS fix while it is
fresh (`LIVE_LOCATION_FRESH_MINUTES = 15`) and otherwise falls back to the
default saved place — a stale fix looks current and is worse than a fixed
address. The answer carries `source` so it can say "from home" rather than
quietly guessing. `saved_places` holds one row: home, 314 Gardeners Road,
Rosebery. Its `lat`/`lng` are NULL, so the address is geocoded per call; filling
them in is a one-row update once a geocoder is reachable.

- [x] 4a — `trip_plan`, `transit_departures`, real-time vs timetable
- [x] 4b — ranking, alternatives, `format_journeys`
- [x] 4c — `leave_by`, `travel_watch`, `travel_alerts`, startup checks
- [x] 4d — **the search** (below)
- [ ] **Prove it.** Nothing here has planned a real Sydney trip yet. Needs
      `OPENROUTESERVICE_API_KEY` and a worker restart; the banner's
      `[worker] TfNSW: ✓` line is the answer four rounds of work rest on.
- [ ] 4e — disruption alerts, and learning regular destinations from calendar
      history

**4d — it searches now, rather than asking once.** One query returns five
departures along the corridor TfNSW picked, which is why ranking them could
never beat Maps: it never considered a second route. Four searches now run
concurrently and pool their results — baseline, bus-biased (rail excluded,
forcing nearby stands), rail-biased (bus excluded, forcing the station), and
park-and-ride.

**The constraint that shaped it.** Asking TfNSW for a trip "from Green Square
Station" returns a journey beginning on the platform; the walk or drive to
reach it is not in the response. Ranked against a baseline whose access walk
*is* counted, that option wins on false pretences and sends you after a train
you cannot reach. So every search but park-and-ride keeps the real origin and
lets TfNSW cost the access itself; park-and-ride cannot, so `add_access_leg`
puts the drive back explicitly. A test pins the failure directly — an option
that wins without its drive leg loses with it.

`verify_journeys` is the "calculate and verify" step that did not exist:
departures already past, arrivals after the deadline, and park-and-ride that
loses to simply driving are all dropped before ranking. Driving time is always
shown for comparison, and park-and-ride states that parking availability is
unchecked, because no feed covers it.

`travel_watch` stopped re-planning every located event on every tick — the
`travel_alerts` row now separates what was *planned* from what was *sent*, so
an event five hours out is planned once and revisited as it nears. `alerted_at`
is still written only after a successful push, so a failed notification still
retries. The job runs the cheap baseline and escalates only when it looks poor.

**Startup checks exist because a key being set proved nothing.** `check_tfnsw`
and `check_openrouteservice` call the live APIs and print a ✓/✗ banner. They are
also the only part of the travel code with no test coverage, by necessity.

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
4. **Traces are still destroyable.** `agent_turns.message_id` is
   `ON DELETE CASCADE` and `cold_storage_archive` hard-deletes, so clearing the
   chat wipes the telemetry with it — which already happened once, taking every
   trace from before 2026-09-02. `ON DELETE SET NULL` is a one-line migration
   and the trace view already renders `(message deleted)` for orphans.
5. **The dormancy was 60 days, not twelve weeks.** The last commit is
   2026-06-06 but `mac_heartbeat.last_seen` reads 2026-07-01 — the worker ran
   for three and a half weeks after the code went quiet. Worth remembering when
   reasoning about what "still worked" at the end.
