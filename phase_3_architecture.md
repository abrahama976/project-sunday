# Phase 2: The Proactive Life Engine — Architecture Document

> This document tracks the full implementation plan for Phase 2.
> Updated at each step. Last updated: **2026-06-03T18:10 AEST**

---

## Progress Tracker

### ✅ Step 1: Database Upgrades
- [x] `tasks` table: Added `tags text[]`, `flexibility_score smallint`, `is_archived boolean`
- [x] `health_logs` table: Added `meal_type text`, `description text`, `water_ml integer`
- [x] `user_location` table: Created (id, user_id, lat, lng, timezone, updated_at)
- [x] `message_summaries` table: Created (id, user_id, summary, message_count, date_from, date_to)
- [x] `messages` table: Added `is_deleted boolean` for soft-delete
- [x] Seeded 3 new scheduled jobs: `meal_checkin`, `nightly_maintenance`, `calendar_prep`
- [x] Migration file: `supabase/migrations/20260603100000_phase2_proactive_engine.sql`

### ✅ Step 2: Stability Fixes
- [x] Auth guard verified: `src/proxy.ts` is the correct convention for Next.js 16 (deprecated `middleware.ts`). Confirmed working via `next build` — shows `ƒ Proxy (Middleware)` in route table.
- [x] Replaced `dangerouslySetInnerHTML` in Dashboard with `react-markdown`
- [x] Added `--color-brand` and `--color-surface-hover` CSS variables to `globals.css`
- [x] Fixed stale closure in approvals (`approveById` wrapped in `useCallback`)
- [x] Removed hardcoded "Alstone" — reads name from `user_profile` or auth email

### ✅ Step 6: Android Location Bridge
- [x] Created `POST /api/location` route at `apps/web/src/app/api/location/route.ts`
- [x] Accepts `{ lat, lng, timezone }` with `x-sunday-secret` header auth
- [x] Upserts into `user_location` table via service role client

### ✅ Step 3: News Feeds Update (COMPLETED)
- [x] Add Mint, Times of India, The Hindu RSS feeds to `DEFAULT_FEEDS`
- [x] Add web_search fallback for India/Singapore/Oman news in morning briefing
- [x] Keep existing feeds: HN, TechCrunch, ABC AU, SMH, Guardian AU, Entrepreneur

### ✅ Step 4: Proactive Scheduler Jobs (COMPLETED)
- [x] `meal_checkin` — 1PM + 7PM UTC, calendar-aware
- [x] `nightly_maintenance` — 3AM local: archive tasks, compress messages, clean health_logs
- [x] `calendar_prep` — 8AM local: prep tasks + travel estimates for today's events

### ✅ Step 5: Brain-dump Task Parsing (COMPLETED)
- [x] Detect multi-item messages in router.py
- [x] Dedicated Gemini call to extract tasks with tags + flexibility_score
- [x] Batch insert via task_create, confirm back in chat

### ✅ Step 7: Health UI Dashboard (COMPLETED)
- [x] Create mobile-first Next.js page at `/health`
- [x] Read `health_logs` for today's entries (Water, Meals, Sleep)
- [x] Quick-action buttons to manually log Water and Meals
- [x] Link from `/more` hub

---

## New Table Schemas

### user_location
```sql
CREATE TABLE user_location (
  id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid        REFERENCES auth.users(id) ON DELETE SET NULL,
  lat         double precision NOT NULL,
  lng         double precision NOT NULL,
  timezone    text        NOT NULL DEFAULT 'Australia/Sydney',
  updated_at  timestamptz NOT NULL DEFAULT now()
);
```

### message_summaries
```sql
CREATE TABLE message_summaries (
  id            uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       uuid        REFERENCES auth.users(id) ON DELETE SET NULL,
  summary       text        NOT NULL,
  message_count integer     NOT NULL,
  date_from     timestamptz NOT NULL,
  date_to       timestamptz NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now()
);
```

### tasks (altered columns)
```sql
ALTER TABLE tasks ADD COLUMN tags text[] DEFAULT '{}';
ALTER TABLE tasks ADD COLUMN flexibility_score smallint NOT NULL DEFAULT 3;
ALTER TABLE tasks ADD COLUMN is_archived boolean NOT NULL DEFAULT false;
```

### health_logs (altered columns)
```sql
ALTER TABLE health_logs ADD COLUMN meal_type text;       -- breakfast/lunch/dinner/snack
ALTER TABLE health_logs ADD COLUMN description text;
ALTER TABLE health_logs ADD COLUMN water_ml integer;
```

### messages (altered columns)
```sql
ALTER TABLE messages ADD COLUMN is_deleted boolean NOT NULL DEFAULT false;
```

---

## New Cron Jobs

| Job Name | Cron Expression | Timezone | Description |
|----------|----------------|----------|-------------|
| `meal_checkin` | `0 13,19 * * *` | UTC | Proactive meal check-in during free calendar windows |
| `nightly_maintenance` | `0 3 * * *` | Australia/Sydney | Archive old tasks, compress messages, clean health_logs |
| `calendar_prep` | `0 8 * * *` | Australia/Sydney | Generate prep tasks and travel estimates for today's events |

---

## New/Modified Executors (Steps 3-5)

| File | Status | Tools | Description |
|------|--------|-------|-------------|
| `executors/news_ops.py` | COMPLETED | Internal | Add 3 India RSS feeds + web_search fallback |
| `jobs.py` | COMPLETED | Internal | Implement 3 new job handlers |
| `router.py` | COMPLETED | Internal | Brain-dump detection + Gemini extraction |

---

## API Routes

### POST /api/location (NEW)
- **Auth**: `x-sunday-secret` header
- **Body**: `{ lat: number, lng: number, timezone?: string }`
- **Response**: `{ ok: true, lat, lng, timezone }`

**curl example:**
```bash
curl -X POST https://your-app.vercel.app/api/location \
  -H "Content-Type: application/json" \
  -H "x-sunday-secret: YOUR_SECRET" \
  -d '{"lat": -33.8688, "lng": 151.2093, "timezone": "Australia/Sydney"}'
```

**Environment variable needed:**
```env
SUNDAY_LOCATION_SECRET=your-random-secret-here
```

---

## Strict Constraints
- ❌ Email sending is prohibited — all email actions go to `/approvals` only
- ❌ Travel calendar blocking is prohibited — AI may suggest, never book
- ❌ Hard deletes prohibited on tasks or messages — soft-delete only
- ✅ All new UI must follow existing dark-mode, mobile-first design at 390px
