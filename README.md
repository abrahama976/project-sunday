# Project Sunday

A hybrid personal AI assistant that runs as a **Next.js PWA** (deployed to Vercel) paired with a **Python worker** running locally on your Mac. All state lives in **Supabase**; the worker polls for messages, routes them through a cascading AI model chain, and executes tool calls autonomously.

## Architecture

```
┌────────────────────┐       ┌──────────────┐       ┌─────────────────┐
│  Next.js PWA       │──────▶│  Supabase    │◀──────│  Python Worker  │
│  (Vercel)          │       │  (Cloud DB)  │       │  (Local Mac)    │
│                    │       │              │       │                 │
│  • Chat UI         │       │  • messages  │       │  • Router       │
│  • Profile Editor  │       │  • actions   │       │  • Executors    │
│  • Settings        │       │  • tasks     │       │  • Scheduler    │
│  • Approvals       │       │  • profiles  │       │  • Google OAuth │
│  • Tasks           │       │  • briefings │       │  • Ollama       │
│  • Dashboard       │       │  • heartbeat │       │                 │
└────────────────────┘       └──────────────┘       └─────────────────┘
```

## Project Structure

```
PersonalAI/
├── apps/
│   ├── web/                  # Next.js 14 PWA (App Router)
│   │   ├── src/app/
│   │   │   ├── page.tsx          # Chat interface (main screen)
│   │   │   ├── approvals/        # Action approval queue
│   │   │   ├── dashboard/        # Morning briefing dashboard
│   │   │   ├── tasks/            # Task management UI
│   │   │   ├── profile/          # AI memory/profile editor
│   │   │   ├── settings/         # Background job toggles
│   │   │   ├── more/             # Settings hub / navigation
│   │   │   ├── inventory/        # Inventory tracking
│   │   │   ├── schedule/         # Calendar/schedule view
│   │   │   └── login/            # Authentication
│   │   └── package.json
│   │
│   └── worker/               # Python async worker (runs on Mac)
│       ├── main.py               # Entry point, message loop, poll loops
│       ├── router.py             # Cascading LLM router (Gemini → Ollama)
│       ├── config.py             # All configuration and tier map
│       ├── scheduler.py          # Cron-like job scheduler
│       ├── jobs.py               # Scheduled job handlers
│       ├── summariser.py         # Auto-profile learning from conversations
│       ├── heartbeat.py          # Supabase heartbeat ping
│       ├── google_auth.py        # Centralised Google OAuth2 management
│       ├── auth.py               # Supabase service role key resolver
│       ├── context/
│       │   └── loader.py         # Profile cache (Supabase → memory)
│       ├── tools/
│       │   └── registry.py       # Gemini function declarations (20 tools)
│       ├── executors/
│       │   ├── calendar_ops.py   # Google Calendar CRUD
│       │   ├── gmail_ops.py      # Gmail search, read, draft, scan
│       │   ├── task_ops.py       # Task CRUD via Supabase
│       │   ├── profile_ops.py    # AI profile updates via Supabase
│       │   ├── travel_ops.py     # Google Maps + TfNSW transit
│       │   ├── web_search_ops.py # DuckDuckGo web search
│       │   ├── web_fetch.py      # URL content fetcher
│       │   ├── file_ops.py       # Local file read/write/list
│       │   ├── news_ops.py       # RSS news fetch & scoring
│       │   └── base.py           # Idempotency & status helpers
│       └── requirements.txt
│
├── supabase/
│   └── migrations/           # 5 migration files
│       ├── 20260429182626_remote_schema.sql
│       ├── 20260429183724_create_base_tables.sql
│       ├── 20260516131651_security_sprint_and_action_queue_upgrade.sql
│       ├── 20260603000000_phase1_foundation_tables.sql
│       └── 20260603000001_create_user_profile.sql
│
└── docs/                     # Architecture documentation
```

## Features (Phase 1 — Complete)

### AI Chat with Cascading Fallback
- **Primary**: `gemini-2.5-flash` — best quality, lowest free quota (20 RPD)
- **Fallback 1**: `gemini-2.5-flash-lite` — higher quota tier
- **Fallback 2**: Local Ollama (`llama3.2:latest`) — unlimited, offline
- **Private mode**: `/private <message>` bypasses Google entirely → Ollama
- Automatic 429/503 error handling with seamless model cascade

### Tool Calling (20 Registered Tools)
| Tool | Tier | Description |
|------|------|-------------|
| `calendar_query` | auto | Query upcoming Google Calendar events |
| `calendar_create` | approve | Create calendar events |
| `calendar_update` | approve | Update calendar events |
| `gmail_search` | auto | Search Gmail inbox |
| `gmail_read_body` | auto | Read full email content |
| `gmail_priority_scan` | auto | Scan for important unread emails |
| `gmail_draft` | approve | Create Gmail drafts |
| `task_create` | auto | Create tasks from conversation |
| `task_update` | auto | Update task status/priority |
| `task_list` | auto | List filtered tasks |
| `web_search` | auto | DuckDuckGo web search |
| `web_fetch` | auto | Fetch URL content |
| `travel_directions` | auto | Google Maps routing |
| `transit_departures` | auto | TfNSW real-time Sydney transit |
| `update_profile` | approve | Update AI memory/profile |
| `file_read` | auto | Read local files |
| `file_list` | auto | List directory contents |
| `file_write` | approve | Write to local files |

### Approval Tiers
- **auto**: Executes immediately, no user confirmation
- **approve**: Queued for user approval in the Approvals UI
- **hold**: Dangerous operations, requires explicit approval

### Background Jobs (Scheduler)
- `morning_briefing` — Daily at 7am AEST
- `email_scan` — Every 30 minutes
- `news_fetch` — Twice daily (6am, 6pm)
- Jobs controlled via `/settings` UI toggles

### Profile Memory System
- Editable Markdown stored in Supabase `user_profile` table
- AI reads profile into system prompt for every message
- Auto-learning: summariser extracts facts every 7 messages
- Profile changes detected via polling (10s interval)

## Setup

### Prerequisites
- Node.js 18+, Python 3.11+
- Supabase project with migrations applied
- Google Cloud OAuth credentials (`credentials.json`)
- Ollama installed with `llama3.2` model pulled

### Environment Variables (`apps/worker/.env`)
```env
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
GEMINI_API_KEY=your-gemini-api-key
GOOGLE_MAPS_API_KEY=your-maps-key        # optional
TFNSW_API_KEY=your-tfnsw-key             # optional
```

### Running
```bash
# Frontend (or deployed to Vercel)
cd apps/web && npm run dev

# Worker (runs locally on Mac)
cd apps/worker
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

## Status

Phase 1 complete. See [walkthrough.md](./walkthrough.md) for details.