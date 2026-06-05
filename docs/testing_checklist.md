# Project Sunday — Integration Test Checklist (Round 4)

## Before starting
- [ ] `claimed_by` migration applied in Supabase SQL editor
- [ ] Worker `.env` has: `GROQ_API_KEY`, `TAVILY_API_KEY`, `NTFY_TOPIC=sunday-abc123`
- [ ] Worker restarted: `bash apps/worker/run_worker.sh`
- [ ] Seed script run: `python3 scripts/seed_profile.py`
- [ ] `scheduled_jobs` INSERT migration run in Supabase SQL editor

## Test 1 — Worker starts clean
- [ ] No import errors in worker output
- [ ] Heartbeat row appears in Supabase within 60 seconds

## Test 2 — Weather fetch
```python
from executors.weather_ops import get_today_weather
import asyncio; print(asyncio.run(get_today_weather()))
```
- [ ] Returns dict with `summary_line` for Sydney

## Test 3 — Ntfy push (fastest test — do this first)
```python
from executors.notify_ops import push
import asyncio; asyncio.run(push("Sunday test", "Hello from Project Sunday"))
```
- [ ] Notification appears on Android within 10 seconds

## Test 4 — Tavily search
```python
from executors.web_search_ops import web_search
import asyncio; print(asyncio.run(web_search("tutoring rates Sydney 2025")))
```
- [ ] Returns formatted results with titles and snippets

## Test 5 — Chat: weather query
- [ ] Open app, type "What's the weather today in Sydney?"
- [ ] Response includes current temperature and conditions

## Test 6 — Daily brief (manual trigger)
Run in Supabase SQL editor:
```sql
UPDATE scheduled_jobs SET last_run_at = '2000-01-01' WHERE job_name = 'daily_brief';
```
- [ ] Within 30 seconds: brief appears on Today dashboard
- [ ] Brief content includes weather line
- [ ] Push notification received on Android

## Test 7 — Profile context
- [ ] In Supabase: `user_profile` table has one row with correct content
- [ ] Ask Sunday: "What do I do for work?" — response mentions tutoring

## Test 8 — Groq fallback smoke test
Run in worker directory:
```python
from budget_gate import pick_model
# (need client and user_id from a running worker session)
```
- [ ] `GROQ_API_KEY` is set in `.env`
- [ ] `budget_gate._groq_available()` returns True

## Test 9 — Notification panel
- [ ] Bell visible in PWA top nav on Android Chrome
- [ ] Tap bell: slide-over opens, shows items
