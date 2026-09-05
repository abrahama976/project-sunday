# Roadmap

The single live plan. Supersedes `phase_3_architecture.md`, `README_NEW.md` and
the Antigravity handover, all of which disagreed with each other and with the
code. If something here is wrong, fix it here rather than starting a new
document.

Last updated: **2026-09-05**

---

## Where things stand

| Component | State | Note |
|---|---|---|
| Supabase | Up | Migrations through `20260905060000`. Every one since `travel_alerts` was applied **directly** — the `Supabase Preview` check is `skipped` on merge, so nothing deploys itself. Prod version stamps therefore differ from the repo filenames |
| `apps/web` | Deployed | Today, **Travel**, Chat, Tasks, Approvals, Schedule, Health, Profile, Traces, Settings. Travel took the Schedule tab; the full week view stays at `/schedule`, linked from Travel |
| `apps/worker` | Running at `5811fda` | `mac_heartbeat.version` reports the running sha, so this row is a lookup rather than an inference — which is the whole reason it exists |
| Google OAuth | **In production** | Re-authorised 2026-09-02 via a Desktop-app client; all services report authorised |
| LLM router | Built | Flash 2.5 → Lite → 2.0 → 2.0-Lite → Groq → Ollama, budget-gated |
| Learning brain | Built | `brain_directives`, approve-tier, capped, superseding |
| Watchdog | **Armed & proven** | Topic set; ntfy returned 200 on a live alert |
| **Agentic loop** | Built | `agent_loop.py`, 5 rounds max, budget-gated per round |
| `agent_turns` | Written | thought / tool_call / tool_result / final / loop_break |
| Agent trace UI | Built | `/traces` — run list, steps in order, termination reason |
| **Travel** | **Working** | 2026-09-05, Rosebery → Moore Park by 7 PM: leave 6:16, arrive 6:52 — eight minutes of slack, not two hours. Bus 358 → Light Rail L2, so cross-mode planning is real. `nearby_services` holds **93 services across 35 stops** including T8 at Green Square. Park-and-ride still unproven end to end |

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
- [x] **The worker reports its commit.** Four fixes were merged, the answers in
      chat did not change, and the obvious reading — that the fixes were wrong —
      was wrong: the worker was running older code and nothing could say so. It
      had to be inferred backwards from model behaviour. `mac_heartbeat.version`
      and the startup banner now carry the git sha, so "is it deployed" is a
      lookup. `+dirty` is included because a modified tree matches no commit,
      and comparing its sha against a merged PR would prove nothing.

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

**4k — a deadline is not the same question as "now".** Asked to reach Kogarah
by 9:00 AM, it answered "leave at 7:01, arrive 7:49, journey 48 minutes" — a
two-hour-early departure and a 48-minute trip in the same breath, and 71
minutes standing on a platform.

Ranking sorted on **earliest arrival**, always. That is right when leaving now
and wrong under a deadline, where every candidate already arrives in time
because the gate rejects the ones that do not — so "earliest" was ranking on a
question nobody had asked. A deadline asks *when do I need to leave*, so the
winner is now the **latest departure that still makes it**.

Latest *arrival* would not have worked: a slow journey can arrive later while
leaving earlier, which is the same bug wearing a different hat. It is pinned as
its own test.

The owner's stated preference was "arrive on time, then least waiting". This
was "arrive on time" implemented as "arrive earliest" — the words matched and
the behaviour did not.

**4l — the car, when there is one.** Three drive-assisted strategies, all
behind an explicit `car_available` flag that is **false by default** and set
only from what the user just said. Never inferred from the profile, never
carried across sessions: whether a car is free this morning is not a durable
fact about a person, and this project has already written one transient fact
somewhere permanent.

| Strategy | Needs | Drives to | Extra cost | Cap |
|---|---|---|---|---|
| `park_ride` | `car_available` | rail and metro **only** | +5 min parking | ≤2 |
| `drop_off` | `drop_off_available` | any boarding point, buses included | 0 | ≤2 |
| `drive_direct` | either | the destination itself | 0 | 1 |

**Two flags, not one.** "I have a car" and "a friend can drop me" are different
permissions, and collapsing them into one boolean would produce exactly the
error this module is otherwise careful about: if somebody else is driving, you
have no car to leave at the station, so offering park-and-ride is as physically
wrong as offering to park at a bus stop. The first version had one flag and got
this wrong; it was the owner asking for "a friend dropping option" that
surfaced it.

The two candidate sets differ because the difference is physical, not
cosmetic. Parking works where there is parking; telling someone to leave a car
at a bus stop is advice that does not survive contact with the bus stop. A
drop-off ends anywhere someone can pull over, so the wider set applies. They
are named for what actually happens — one strands your car at the station, the
other spends somebody else's half hour.

All within 5 km straight-line and 20 minutes' drive, still filtered by
`station_is_toward` so it never drives away from the destination, and still
required to beat the best car-free option by ten minutes.

**Driving door to door has no waiting and no changes**, so on a straight
ranking it wins nearly every time — ten minutes against thirty-seven to Moore
Park. Ranking it honestly is right; letting it be the *only* answer is not,
because a transit planner that says "just drive" has stopped answering the
question. `promote_car_free` leaves the order alone and lifts one option: the
best journey involving no car, to second place. The winner keeps its place on
merit and the car-free plan is always there to compare against.

The driving *comparison line* still prints whether or not a car is available —
the owner's call, and a good one: knowing what you are giving up is useful
even when you cannot take it.

**Two bugs fixed alongside.** Consecutive legs on the same route were counted
as a change, so "the 358, then the 358 again" cost a journey a transfer it
never had. They are one vehicle only when the route matches **and** nothing was
walked between them **and** the gap is under two minutes — because getting off
a 358 to wait twenty minutes for the next 358 is a change by any measure a
passenger cares about, and so is walking to another stop for it. And the walk
radius is now per *service* rather than per stop: one train platform was
lending its 2 km allowance to every bus that happened to call there, which is
how a bus thirty minutes away ended up competing with the one at the corner.

**4m — a page for it, and a plan that outlives the answer.** Everything above
was reachable only by typing a sentence into chat and hoping the model set the
right arguments. `/travel` replaces the Schedule tab with controls.

The blocker was never the UI. `plan_journeys` built ranked options, each tagged
with the strategy that found it, plus every rejection and its reason — and then
`format_journeys` rendered it to a string and the structure was gone. That one
fact is why there could be no page, why a failure collapsed to a single summary
sentence when per-option reasons existed, and why nothing could learn from
where this person actually goes.

`travel_plans` keeps it; `travel_requests` is the inbox. Vercel cannot reach
the Mac, so the page inserts a row and the worker's poll answers it — the same
shape as `action_queue`, roughly three to eight seconds. No model call, so
tapping Plan repeatedly costs nothing against the 250/day cap.

The page shows the leave time largest, because that is the question almost
every trip is really asking; the strategy badge on each card, which is the only
way to see whether the fan-out ran or quietly fell back to one corridor; and
the rejected options with their reasons, which is how the gate's thresholds get
validated against reality instead of staying guesses.

Two things it closes. **The services correction UI** promised in 4e finally
exists — `is_hidden` and `source='user'` shipped in #35 and had no controls, so
the design has been half-built ever since; 93 services across 35 stops is too
many to leave uncurated. And **live location**: `resolve_origin` has always
preferred a phone fix under fifteen minutes old over the saved home, but
nothing in the app ever sent one — `/api/location` existed the whole time with
only a curl example for a caller, and `user_location` was empty. "Start from
where I am" now fills it.

**4b — Ranking.** *(Superseded in part by 4k for deadline queries.)*
Journeys sort on **arrive, then wait, then changes, then
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
- [x] 4e — **the local network** (below)
- [x] 4f — **saving it** (below). Discovery worked; persistence never did
- [x] 4g — **what day it is** (below). Two separate ways the time was wrong
- [x] 4h — **a stop, not an address** (below). Discovery saved a fake stop
- [x] 4i — **which place, and is this journey real** (below). `resolve_place`
      and the plausibility gate
- [x] 4j — **the first real discovery run** (below). 158 stops, rail in the
      pool, and every stop named `undefined, undefined`
- [x] 4k — **a deadline is not "now"** (below). Ranking answered the wrong
      question and sent you out of the house two hours early
- [x] 4l — **the car, when there is one** (below). Park-and-ride, drop-off
      and driving the whole way, behind an explicit car-available flag
- [x] **Proved it.** 2026-09-04, Rosebery → Newtown: leave 7:23 PM, arrive
      7:58 PM, 358 from Lakes Hotel, with the driving comparison. Four attempts,
      each defeated by a different bug — all four are fixed in 4i.
- [ ] **Prove the fan-out.** The trip above came from the *baseline* query
      alone — `nearby_services` still held only the retired fake rows, so no
      boarding-point search ran. Needs a restart carrying 4h.
- [ ] 4j — disruption alerts, and learning regular destinations from calendar
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

**4e — planning from the services that actually exist.** 4d searched by
*excluding modes*, which was the wrong axis twice over. One query still returns
one corridor, so a place served by four routes was offered one of them — the 343
would surface and the 358, the 306 and the metro never entered the pool. And
excluding buses to "force rail" also removed the feeder bus, so *343 to Waterloo,
then the metro* was a journey that search could not return by construction.

So the boarding points are enumerated instead. `nearby_services` holds the
learned local network — stop, route, headsign, frequency, walk time — refreshed
weekly by `refresh_nearby_services` and **correctable**: a row you edit is marked
`source='user'` and discovery never overwrites it, because the API not knowing
about a service you catch daily should not mean Sunday forgets it every week.

`choose_boarding_points` takes **one stop per distinct route**, not the nearest
N. That distinction is the feature: five nearest stops on one road are five
stops on the same bus, and five queries would rediscover what the baseline
already found. Each option is then named by its service ("343 from Gardeners
Rd") and its measured frequency, which is the figure that says what a wait
means — eleven minutes on a ten-minute service is a near miss, on a half-hourly
one it is the morning.

Frequency is the **median** gap between departures, and `None` rather than a
guess when only one departure is visible. Driving stays occasional: park-and-ride
is dropped unless it beats the best car-free option by ten minutes, and the drive
radius is 5 km.

**Startup checks exist because a key being set proved nothing.** `check_tfnsw`
and `check_openrouteservice` call the live APIs and print a ✓/✗ banner. They are
also the only part of the travel code with no test coverage, by necessity.

**A correction, since this document asserted otherwise.** An earlier revision
of the table above said the Mac had "Pulled 2026-09-04 through 4f — discovery
ran and wrote for the first time". That was inferred from ten rows appearing in
`nearby_services`, and it was wrong. The Mac has been at #37 throughout. The
rows appeared because the *migration* below was applied directly to production,
and #37 already contained the `on_conflict` upsert — so the old code started
writing the moment the constraint existed. The code half of 4f has never run.
Rows appearing is evidence about the database, not about the checkout, and the
two were conflated here.

**4f — the local network is saved, not just found.** 4e shipped with a key
PostgREST cannot target. `nearby_services_unique_idx` was an *expression* index
on `COALESCE(headsign, '')`; supabase-py's
`on_conflict="user_id,place_label,stop_name,route,headsign"` reaches Postgres as
a plain column list, and Postgres will not match a plain list to an indexed
expression. Every write failed `42P10`. Discovery found **306, 309, 343, 358,
N20** near Gardeners Rd and stored **zero rows**, so every trip fell straight
back to the single baseline query 4e existed to replace.

The COALESCE was there to make `NULL` and `''` collide, since two NULLs do not
conflict under a plain unique index and each weekly run would duplicate every
unlabelled service. Removing the NULL is the better answer: discovery already
writes `''` for "no destination shown", so `headsign` is now `NOT NULL DEFAULT
''` under a plain unique **constraint**.

The SQL test that should have caught this wrote `ON CONFLICT (…, COALESCE(
headsign, ''))` — matching the index rather than the caller. Legal from psql,
and not a statement the client is capable of sending, so it passed against a
schema on which every real write failed. Its replacement issues the upsert in
the client's shape, and asserts a `pg_constraint` row rather than merely an
index, because only the plain-column form appears there.

The job also lied on the way out: it printed the routes it had found and a count
of zero saved, in the same cheerful line. It now says outright that it saved
none of them, and what that costs.

**4g — what day it is.** Two independent time bugs, either of which is enough to
answer the wrong question convincingly.

*The prompt had no date.* `build_system_prompt()` stated none, so the model
dated from its training data: "Blacktown tomorrow 7am" became `2024-05-15`, and
TfNSW answered a question about May 2024 without complaint. Every briefing
prompt in `jobs.py` already carried a date; the chat path — the only one that
takes relative dates from a human — was the one without. It now opens with a
`NOW:` line, rebuilt per call (`context/loader.py` caches the database reads,
not the prompt string, so there is no stale copy to invalidate at midnight).

*A naive time was read as UTC.* The subtler one, and it survived the first fix.
Asked for 7am, a model writes `2026-09-05T07:00` with no offset. `_parse_time`
is right to call that UTC — every TfNSW timestamp carries a zone — and wrong
for anything a model writes: `_trip_params` converted it to **17:00** in Sydney
and planned the trip, correctly and uselessly, for five in the afternoon. So
user-supplied times go through `parse_user_time`, where a bare wall-clock time
means the wall clock the user is looking at. An explicit offset is still obeyed.

A prompt is a request, not a guarantee, so `check_requested_time` runs in
`plan_journeys` — the one chokepoint both `trip_plan` and `leave_by` pass
through — before anything is looked up or fetched. It refuses a time already
past, naming the date it read so the mistake is visible, and refuses an
unreadable one rather than dropping it silently: a dropped `arrive_by` turns
"get me there by 9" into "leave now", which looks like an answer and is not the
one that was asked for. Pure, so both sides of the boundary are pinned in tests
without a network.

**4h — a stop, not an address.** 4f made discovery able to save. What it saved
was one fake stop.

`_find_stops` asked `stop_finder` with `type_sf=coord`. That call reverse-
geocodes: it handed back the address itself as a single pseudo-location,

    coord:4888949:3761579:GDAV:314 Gardeners Rd, Rosebery:0

at the user's own front door. So the radius filter had nothing to filter, and
all ten discovered services were attributed to that one id — every `walk_min`
0, every mode a bus, Green Square (1.3 km, inside the 2 km rail radius) and the
metro never considered, because no real stop was ever in the list. The
boarding-point fan-out then fired five near-identical queries from one point,
which is precisely the single-corridor behaviour 4e existed to replace.

It hid because `departure_mon` accepts a `coord:` id and answers with a
proximity scan, so the routes that came back were real: 301, 303, 306, 309,
343, 358 all genuinely run past that address. And the startup banner said
`TfNSW: ✓` throughout, because `check_tfnsw` searches by *name*, which works.
A passing check that proves a different thing — the same shape as the SQL test
in 4f.

Discovery now asks `/v1/tp/coord`, the endpoint whose question is "what is near
this point", and falls back to `stop_finder`. Both paths run through
`_stops_from_locations`, which drops pseudo-ids, so the fallback cannot
reintroduce the bug and a wrong guess at the coord parameters degrades to
"found nothing" — non-destructive, since the job leaves the inventory alone
when it finds nothing.

Two loose ends closed with it. `load_nearby_services` drops pseudo-id rows on
read, so a fixed discovery cannot lose to the data the broken one left behind;
and the startup bootstrap counts rows keyed to a *real* stop, so ten retired
fake ones no longer look like a local network and suppress the run that
replaces them.

**4i — which place, and is this journey real.** One question, "how do I get to
Newtown", took four attempts on 2026-09-04. Each was defeated by a different
thing, and the trace has all four.

*"Newtown" resolved to the wrong Newtown.* `_tfnsw_geocode` took the **first**
candidate carrying a parseable coordinate, whatever it was — the same bug that
made "Sans Souci" resolve near Narrabri. EFA returns `isBest`, `matchQuality`,
`type` and a coordinate, and all four were being discarded. `travel/resolve.py`
now uses them: the provider's own best answer first, then its match score, then
kind, then proximity to the origin — which is what turns a 500 km candidate
from an answer into a rejection. Ambiguity is only raised when survivors
genuinely tie *and* sit far enough apart to be different places, because a
question the user has to answer is a worse outcome than a right answer. Two
entrances to one station do not count.

*`origin: "home"` was sent to TfNSW as free text.* Omitting the origin had
always worked — that path reads `saved_places`. Naming it did not, because this
path did not, so the literal string matched some other Home in NSW and produced
a journey **leaving at 6:20 PM to arrive at 3:07 PM**: 1248 minutes, 783 of them
waiting. `resolve_saved_label` closes the gap; both ways in now reach the same
lookup.

*And it was offered as the best option.* Nothing between the provider and the
answer had an opinion about whether a journey was survivable. `travel/gate.py`
is that opinion — pure arithmetic on numbers `summarise_journey` already
produces, so it costs no request and stays explainable. Arrival before
departure, a single wait over 90 minutes, waiting more than half the trip, more
than four times the driving estimate, arriving on a day nobody asked about, a
departure already past, arrival after the deadline. The rules overlap
deliberately: the Werris Creek itinerary fails four of them independently, and
the gate should not depend on knowing which upstream bug produced its input.
Rejections carry their reason, so the failure message says *what was wrong*
rather than "none of them work", which only invites the same question again.

**4j — the first real discovery run, and what it exposed.** 2026-09-05, the
first time any of 4f–4i executed. `coord(STOP)` returned **158 stops** — the
endpoint parameters were right — and rail entered the pool for the first time:
**T8 at Green Square on a 4-minute headway**, alongside twelve bus routes
instead of one corridor.

It also wrote `undefined, undefined` as the name of every one of them. EFA's
`/v1/tp/coord` does not put a stop's name where `stop_finder` does, and the
placeholder was taken at face value. Not merely ugly: `stop_name` is part of
the upsert key, so all 158 stops collided and **21 rows survived under a single
name**. `stop_display_name` now tries `disassembledName`, `name`, the parent,
then `properties`, rejects EFA's placeholders explicitly, and falls back to the
**stop id** rather than to an empty string — because an id is unique by
construction, so the worst case is an ugly label instead of merged rows.

The count in the log said the call worked; only a name says the rows will be
usable, so the line now prints the nearest stop's name and warns when the id
fallback fires.

Also fixed alongside: `_nearby_stations` had the same `type_sf=coord` bug as
discovery, returning the address, whose product class is bus — so the rail
filter rejected it and **park-and-ride has never produced a single candidate**,
silently, because an empty list also looks like "no station nearby".

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
