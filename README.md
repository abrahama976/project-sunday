# Project Sunday

A personal AI assistant. Next.js PWA on Vercel for the interface, a Python
worker on a Mac for the actions, Supabase in between holding all state.

Built to run at zero recurring cost: Gemini's free tier as the primary brain,
with a cascade down through Groq to local Ollama when the daily budget runs out.

> **Status.** The worker is not currently running and Google OAuth tokens have
> expired. See [ROADMAP.md](./ROADMAP.md) for what is built, what is not, and
> the order to bring it back.

---

## Architecture

```
┌──────────────────┐      ┌──────────────┐      ┌──────────────────┐
│  Next.js PWA     │─────▶│  Supabase    │◀─────│  Python worker   │
│  (Vercel)        │      │  (Postgres)  │      │  (local Mac)     │
│                  │      │              │      │                  │
│  Today · Chat    │      │  messages    │      │  LLM router      │
│  Tasks · Schedule│      │  action_queue│      │  20 executors    │
│  Approvals       │      │  tasks       │      │  cron scheduler  │
│  Profile · Brain │      │  user_profile│      │  Google OAuth    │
│  Health · More   │      │  brain_…     │      │  Ollama fallback │
└──────────────────┘      └──────────────┘      └──────────────────┘
                                 │
                                 └── pg_cron watchdog → ntfy → phone
```

The two halves never talk directly. The web app writes rows; the worker polls
for them, acts, and writes rows back. That means the UI stays up when the Mac
is asleep — and it also means nothing happens while the Mac is asleep, which
the watchdog exists to tell you about.

---

## The two memory layers

Sunday remembers in two distinct ways, and keeping them apart is deliberate.

| | **Profile** | **Brain** |
|---|---|---|
| Holds | Facts about you | Rules about how to serve you |
| Example | "Lives in Sydney" | "Keep answers under three sentences" |
| Stored as | Markdown in `user_profile` | Rows in `brain_directives` |
| Written by | `update_profile` | `brain_learn` |
| Edited at | Profile | Profile → Learned rules |

Facts are read and rarely revised, so a markdown blob suits them. Rules get
contradicted, refined and retired, which a blob cannot express — you cannot
supersede a bullet inside one, record where it came from, or retire it without
losing the history.

### How the brain learns

Tell Sunday how you want something done — *"keep it shorter"*, *"always show
code first"*, *"stop suggesting news at night"* — and it proposes a rule. You
approve it, and it applies from then on. The summariser also proposes rules
from observed patterns every seven messages, capped at two per run.

Learned rules are appended to the system prompt after `brain_growth.md` and win
where they conflict with a default. Four constraints keep a self-modifying
prompt safe:

1. **Approve-tier.** Nothing lands without your tap.
2. **User-sourced only.** A rule may come from what you said or from the
   summariser watching you. Never from a fetched page, an email body, or tool
   output — otherwise `web_fetch` becomes a persistent prompt-injection vector.
   Enforced in the executor *and* by a `CHECK` constraint in the schema.
3. **Capped.** 40 rules, 6000 characters. This text rides on all 250 daily
   requests, so growth is a budget cost.
4. **Superseding, not stacking.** A restatement replaces the old rule rather
   than sitting beside it.

`apps/worker/context/brain_growth.md` is the constitution: hand-written,
version-controlled, never machine-edited.

---

## Approval tiers

No write happens without a tap. Tools are classified in `config.py`:

- **`auto`** — executes inline. Reads, plus task create/update.
- **`approve`** — queued to `action_queue`, waits for you in Approvals.
  Calendar writes, Gmail drafts, profile and brain writes, reminders.
- **`hold`** — declared but not exposed to the model at all. Deletes, sending
  email, shell. Present so that if they are ever added to the registry they
  already carry a safe tier.

---

## Repository layout

```
apps/
  web/                  Next.js PWA (App Router, TypeScript, Tailwind)
    src/app/
      page.tsx          Today — the home screen
      chat/             Conversation
      approvals/        Pending actions, with per-type preview cards
      profile/          Profile editor + the learned-rules panel
      tasks/ schedule/ health/ inventory/ settings/ more/
  worker/               Python 3.13 asyncio worker — local Mac only
    main.py             Entry point, poll loops, action dispatch
    router.py           Cascading LLM router + system prompt assembly
    budget_gate.py      The only path to an LLM call; enforces daily caps
    scheduler.py        Cron scheduler, honours per-job timezones
    jobs.py             Scheduled job handlers
    summariser.py       Extracts facts and proposes rules, one call per run
    executors/          One module per tool family
    context/
      brain_growth.md   The constitution (static)
      loader.py         Caches profile + directives for the prompt hot path
    tests/              Dependency-free unit tests — python3 tests/test_brain.py
supabase/
  migrations/           Schema history
  tests/                SQL suites — ./supabase/tests/run.sh
docs/
  sprint_3_design.md    Agentic loop design (not yet implemented)
```

---

## Running it

### Prerequisites
Node 18+, Python 3.11+, a Supabase project with migrations applied, Google
OAuth credentials (`credentials.json`), and Ollama with `llama3.2` pulled.

### Environment — `apps/worker/.env`
```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=...
GEMINI_API_KEY=...
GROQ_API_KEY=              # optional — cascade tier below Gemini
GOOGLE_MAPS_API_KEY=       # optional — travel_directions
TFNSW_API_KEY=             # optional — Sydney transit
TAVILY_API_KEY=            # optional — web_search
NTFY_TOPIC=                # push notifications
```

### Start
```bash
# Frontend
cd apps/web && npm install && npm run dev

# Worker
cd apps/worker
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

The worker is normally managed by `launchd` via
`apps/worker/com.projectsunday.worker.plist`, which restarts it when it exits.

### The watchdog
After applying migrations, set your ntfy topic once — the watchdog stays inert
until you do:

```sql
INSERT INTO public.watchdog_config (id, ntfy_topic)
VALUES (1, 'your-topic-here')
ON CONFLICT (id) DO UPDATE SET ntfy_topic = EXCLUDED.ntfy_topic;
```

It then checks every 5 minutes and pushes to your phone if the worker goes
quiet for 15.

---

## Tests

```bash
python3 apps/worker/tests/test_brain.py     # brain logic, no dependencies
./supabase/tests/run.sh                     # watchdog + schema, throwaway PG
```

---

## Constraints

These are standing rules for the project, not preferences:

- Email is never sent, only drafted.
- Tasks and messages are soft-deleted, never hard-deleted.
- `budget_gate.py` is the only path to an LLM call.
- The AI may suggest calendar changes, never book them unattended.
- UI is dark-mode, mobile-first, 390px baseline.
