# Windows runbook — the worker in Docker

The worker moved off the Mac because the Mac is not always on. It now runs in a
Docker Desktop container on the Windows laptop, which stays on. Ollama runs
**natively** on Windows (CUDA) and the container talks to it over
`host.docker.internal:11434`.

The Mac path still exists and is still supported as a fallback — see
[Rollback](#rollback-to-the-mac). Nothing here deletes
`apps/worker/com.projectsunday.worker.plist` or `run_worker.sh`.

---

## 0. What runs where

| Piece | Runs | Notes |
|---|---|---|
| Next.js PWA | Vercel | unchanged |
| Supabase | hosted | unchanged |
| Worker | **Docker container, Windows laptop** | this document |
| Ollama | **native on Windows** | not containerised: the GPU is the point |
| Worker (fallback) | Mac, `launchd` | see Rollback |

Secrets do **not** live in the image or in the repo. They are:

- `apps/worker/.env` — Supabase URL and service-role key, `GEMINI_API_KEY`, and
  the optional `GROQ_API_KEY`, `TAVNSW`/`TFNSW_API_KEY`,
  `OPENROUTESERVICE_API_KEY`, `NTFY_TOPIC`, `TAVILY_API_KEY`. Copied by hand.
- `apps/worker/credentials.json`, `apps/worker/token_calendar.json`,
  `apps/worker/token_gmail.json` — Google OAuth. Copied by hand.

Copy them by hand, over the network you trust, and never through git, chat, a
screenshot or a paste into a ticket. All of them are in `.gitignore` and in
`.dockerignore`; if either list loses one of those lines, the secret ends up in
an image layer and `docker history --no-trunc` will print it.

---

## 1. One-time install

1. **Docker Desktop** — WSL 2 backend, then Settings → General → **Start Docker
   Desktop when you sign in**, and Settings → Resources → WSL integration on.
   Without the first, nothing restarts after a reboot and the worker is silently
   gone until someone opens Docker.
2. **Git for Windows** — the clone is how you deploy.
3. **Ollama for Windows** — native install, then pull the models the fallback
   route uses:
   ```
   ollama pull llama3.2:latest
   ```
   The worker only uses Ollama when the Gemini tiers are exhausted, so a missing
   model degrades a busy day, not a normal one. `main.py` prints what it found at
   startup and says so plainly if the model is absent.
4. **Cap WSL's memory.** Docker Desktop runs in WSL 2 and will otherwise take
   half the laptop's RAM. Create `%UserProfile%\.wslconfig`:
   ```
   [wsl2]
   memory=4GB
   ```
   Then `wsl --shutdown` (this stops Docker; reopen Docker Desktop afterwards).
5. **Clone** (main only — this is a runtime clone, not a development one):
   ```
   mkdir C:\dev
   git clone https://github.com/abrahama976/project-sunday.git C:\dev\project-sunday
   ```

---

## 2. First start

1. Copy the three Google files and `.env` into `C:\dev\project-sunday\apps\worker\`.
   They must exist **before** the first `up`: these are bind mounts, and Docker
   creates a *directory* at the mount point when the source is missing, which
   then fails the container with "is a directory" and is confusing to undo.
2. Check Ollama is up and the container can see it:
   ```
   curl http://localhost:11434/api/version
   ```
3. Build and start, from `C:\dev\project-sunday`:
   ```
   set GIT_SHA=%COMPUTERNAME%
   docker compose up -d --build
   ```
4. Watch the first minute. The startup banner is deliberately loud — it states
   the version, whether Google tokens are valid, whether the ntfy topic is set,
   whether TfNSW and OpenRouteService answer, and which Ollama models exist:
   ```
   docker compose logs -f worker
   ```
   Look for `[worker] ready. Listening for messages, approvals, and scheduled jobs.`
5. Confirm health, which is the age of the heartbeat file rather than "is a
   process running":
   ```
   docker compose ps
   ```
   `STATUS` should read `Up ... (healthy)`. `unhealthy` means the poll loop
   stopped touching its file — check the logs for a hung Supabase call or a
   crash loop.

Scheduled jobs are read from `scheduled_jobs` in Supabase, so they need no
Windows setup. The watchdog (pg_cron → ntfy) is unchanged and still watches the
`mac_heartbeat` row the worker writes; the row is named for the Mac but it is the
worker's heartbeat wherever it runs.

---

## 3. Update

```
cd C:\dev\project-sunday
git pull
docker compose up -d --build
docker compose logs --tail 40 worker
```

The first log line carries the version and `GIT_SHA`, so "did the update
actually deploy?" is answered by reading it rather than by inferring from bugs
that persist.

Nothing is stored inside the container. `./data`, the token files and `logs/`
are mounts, so `up --build` throws the old container away and keeps every byte
that matters. `docker compose down` does the same; `docker compose down -v` is
not needed here and would only be relevant if a named volume existed.

---

## 4. Logs

```
docker compose logs -f worker            # follow
docker compose logs --tail 200 worker    # last 200 lines
docker compose logs --since 2h worker    # since a point in time
```

The worker prints to stdout (`PYTHONUNBUFFERED=1`), so `docker compose logs` is
the real log. `apps/worker/logs/` is mounted for parity with the Mac checkout
and is not where the interesting output goes. Docker's JSON log is capped at
3 × 10 MB by `docker-compose.yml`; on a machine that stays on for months,
uncapped it would fill the disk.

Agent traces are not in the log at all — every step of every answer is a row in
`agent_turns`, read back in the app at **More → Traces**.

---

## 5. When something is wrong

| Symptom | Look at |
|---|---|
| `unhealthy` but `Up` | `docker compose logs worker` for a stuck `[poll]` or a 401 loop; the loop touches its heartbeat every 2s, so a gap means it is wedged |
| Container restarting | `docker compose logs --tail 100 worker`. `sys.exit(1)` on a dead background task is by design — the restart is the recovery, but the *reason* is in the log above it |
| `[worker] Ollama: ✗ (not reachable)` | Ollama not running on the host, or `OLLAMA_HOST` changed. `curl http://localhost:11434/api/version` on Windows; inside the container it must be `http://host.docker.internal:11434` |
| Google `✗ (re-auth needed)` | Tokens expired. Run `python3 auth_setup.py` **on the Mac** (it is the only place the browser flow is allowed to run), then copy the refreshed `token_*.json` files across and restart |
| `KEYERROR`/`KeyError` at startup on `SUPABASE_URL` | `.env` missing or not mounted. `config.py` reads those at import time and fails immediately, which is the intended behaviour |
| Everything answers "budget exhausted" | That is the cascade working, not a fault. Check whether the daily caps in `config.py` were actually exhausted, or whether a provider key is missing |

`docker compose exec worker python -c "..."` works for a quick probe — the
image has a Python interpreter but no `ps`, `grep` or shell utilities.

---

## 6. Rollback to the Mac

The Mac path was kept working on purpose. To go back:

1. On the Windows laptop: `docker compose down`. Optionally
   Settings → General → untick "Start Docker Desktop when you sign in", so it
   does not come back on its own.
2. On the Mac, in `~/Developer/project-sunday` (formerly
   `~/Projects/PersonalAI`; the symlink keeps the plist's paths valid):
   ```
   git pull
   launchctl load ~/Library/LaunchAgents/com.projectsunday.worker.plist
   ```
3. Confirm the Mac worker is the one writing heartbeats — only one worker should
   run at a time. Two workers both poll `messages` and both claim work; the
   `claimed_by` guard makes that mostly safe rather than correct, so do not leave
   both up "just in case".

No data migration is involved: all state is in Supabase. The only thing the
laptop holds is the container, its logs and `./data`.
