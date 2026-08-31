# Runbook

Operational procedures. Manual steps that cannot live in code.

---

## 1. Publish the OAuth consent screen to Production

**Why:** Google expires refresh tokens after 7 days when publishing status is
`Testing` and user type is `External`. That is the root cause of the recurring
Google auth failures — roughly twelve expiries across this project's life.

**The key fact:** the 7-day expiry is tied to **publishing status**, not to
verification status. Publishing to production stops it. Verification is a
separate axis that controls the warning screen and the user cap, and is *not*
required to stop the token expiry.

### Steps

1. Open [Google Cloud Console](https://console.cloud.google.com/) and select the
   Project Sunday project.
2. Go to **APIs & Services → OAuth consent screen**. In the newer console this
   is branded **Google Auth Platform → Audience**.
3. Publishing status will read **Testing**. Click **Publish app**.
4. Confirm the dialog. The console may warn that your scopes need verification
   and offer to start that process — **you can publish without submitting for
   verification.** Do not start the verification flow; you do not need it.
5. Status should now read **In production**.

### Then re-authorise — this step is not optional

**A token minted while the app was in Testing keeps its 7-day fate.** Publishing
does not heal existing tokens. If you skip this, everything looks correct and
your tokens still die next week.

```bash
cd apps/worker
rm -f token_calendar.json token_gmail.json   # whatever google_auth.py wrote
source .venv/bin/activate
python3 main.py                              # triggers the OAuth flow
```

Approve both consent flows in the browser. The worker prints token status per
service on startup:

```
[worker] Google calendar: ✓
[worker] Google gmail: ✓
```

### What you will see at the consent screen

This project requests one sensitive scope (`calendar.events`) and two
**restricted** ones (`gmail.readonly`, `gmail.compose`). Unverified, that means:

- **"Google hasn't verified this app"** on the consent screen. Click
  **Advanced → Go to Project Sunday (unsafe)**. Expected, and harmless for an
  app you wrote and run yourself.
- **A 100-user cap** for the lifetime of the project. Irrelevant at one or two
  users, and it cannot be reset — so do not burn it by testing with throwaway
  accounts.

Full verification (including a CASA Tier 2 security audit for the Gmail scopes)
only buys you the removal of that warning and the cap. Not worth it here.

---

## 2. Apply migrations and arm the watchdog

### Apply the migrations

Four new migrations, in filename order:

```
20260828120000_fix_heartbeat_status.sql      mac_heartbeat.status (idempotent)
20260828130000_fix_job_timezones.sql         scheduler timezone corrections
20260828140000_heartbeat_watchdog.sql        pg_cron + pg_net watchdog
20260828150000_create_brain_directives.sql   the learning brain
```

```bash
supabase db push
```

Or paste each into the Supabase SQL editor in that order.

`20260828140000` needs the `pg_cron` and `pg_net` extensions. It creates them
itself; if your project blocks that, enable both under **Database → Extensions**
first and re-run.

### Set the ntfy topic

The watchdog ships inert on purpose — it has no topic, so it does nothing until
you give it one.

**ntfy.sh topics are public.** Anyone who knows the name can read your
notifications and publish to them, and these carry worker status. Use a long
random name, never something guessable like `sunday-alerts`.

```sql
INSERT INTO public.watchdog_config (id, ntfy_topic)
VALUES (1, 'sunday-ergz45jgiig5fwcokc7fan')
ON CONFLICT (id) DO UPDATE SET ntfy_topic = EXCLUDED.ntfy_topic;
```

Then subscribe on your phone: install the ntfy app, **Add subscription**, enter
the same topic name.

Reusing the worker's existing `NTFY_TOPIC` is fine and arguably better — one
channel you are already subscribed to. Use whatever is in `apps/worker/.env`
rather than the value above if you would rather not add a second subscription.

### Smoke test — free, because the worker is already down

The worker is not running, so its heartbeat is already stale. Setting the topic
is the whole test:

1. Set the topic as above.
2. Within 5 minutes your phone gets **"Sunday worker is down"** at high
   priority, naming how long it has been quiet.
3. Start the worker.
4. Within 5 minutes you get **"Sunday is back"** at low priority.

Two pushes proves both halves of the state machine — the alert and the
recovery-with-latch-clear. If neither arrives, check in order:

```sql
-- Is the topic actually set and the watchdog enabled?
SELECT ntfy_topic, enabled, last_alerted_at FROM public.watchdog_config;

-- Is the cron job registered?
SELECT jobname, schedule, active FROM cron.job
 WHERE jobname = 'worker-heartbeat-watchdog';

-- Did the HTTP calls go out, and what came back?
SELECT * FROM net._http_response ORDER BY created DESC LIMIT 5;

-- Force a run rather than waiting for the next tick.
SELECT public.check_worker_heartbeat();
```

### Tuning

```sql
-- Alert sooner or later than 15 minutes of silence.
UPDATE public.watchdog_config SET stale_after = '30 minutes' WHERE id = 1;

-- How long before a still-down worker nags again. Default 6 hours.
UPDATE public.watchdog_config SET realert_after = '12 hours' WHERE id = 1;

-- Silence it entirely, e.g. while travelling without the Mac.
UPDATE public.watchdog_config SET enabled = false WHERE id = 1;
```

---

## 3. Re-authorising Google later

Publishing to production makes refresh tokens indefinite, but they still die if
you revoke access, change your Google password, go 6 months unused, or exceed
the per-client token limit. When the worker logs
`✗ (re-auth needed)` or an `invalid_grant`:

```bash
cd apps/worker
rm -f token_*.json
source .venv/bin/activate && python3 main.py
```

If this starts happening weekly again, check that publishing status has not
reverted to Testing — that is the signature of the 7-day expiry.
