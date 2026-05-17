# Project Sunday

A personal AI assistant built as a PWA (Progressive Web App), accessible from any device via browser. Designed to be modular, self-improving, and deeply integrated with your daily life.

## What it does

- Answers questions via natural language chat
- Reads Gmail and Google Calendar on request
- Manages an approval queue for actions that need human sign-off
- Tracks inventory items
- Displays a personal dashboard
- Routes all requests through a local AI worker (Gemini)

## Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16 (App Router, Turbopack), deployed on Vercel |
| Database | Supabase (Postgres + Realtime) |
| Auth | Supabase Auth with Google OAuth |
| Worker | Python 3 asyncio process |
| AI Model | Google Gemini API |
| Monorepo | `apps/web` (frontend) + `apps/worker` (backend) |

## Project Structure
apps/
web/ # Next.js PWA frontend
worker/ # Python AI worker
main.py # Entry point, polling loop
router.py # Gemini intent routing
summariser.py # Conversation summarisation
config.py # Environment config
executors/ # Tool implementations (Gmail, Calendar, file ops...)
tools/ # Tool registry (schema definitions for Gemini)
context/ # User profile loader

text

## Running locally

```bash
# Frontend
cd apps/web && npm install && npm run dev

# Worker
cd apps/worker && pip install -r requirements.txt && python main.py
```

Requires `.env.local` in `apps/web` and environment variables set for the worker. See project documentation for details.

## Status

Active development. Core features working. See roadmap for planned additions.
