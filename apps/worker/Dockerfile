# Project Sunday worker — runtime container for the Windows laptop.
#
# Deliberately small. This image runs a poll loop against Supabase plus a
# handful of HTTPS APIs; it needs no compiler, no git and no shell tooling.
FROM python:3.13-slim

# tzdata is NOT in the slim base image, and config.py resolves
# ZoneInfo("Australia/Sydney") at startup — without it the worker dies before
# its first poll with ZoneInfoNotFoundError. ca-certificates is for TLS.
RUN apt-get update && apt-get install -y --no-install-recommends \
      tzdata \
      ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=Australia/Sydney \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Dependencies before source, so editing a .py file does not reinstall them.
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Source only. .dockerignore excludes .env, .env.*, credentials.json and
# token_*.json: secrets arrive at runtime through env_file and bind mounts, and
# must never exist in an image layer where `docker history --no-trunc` can read
# them back. See docs/windows-runbook.md.
COPY . /app/

# The commit that is actually running, printed in the first log line by
# version.py. Same reason the heartbeat carries a version: "is the fix deployed?"
# should never need to be inferred from model behaviour.
ARG GIT_SHA=unknown
ENV GIT_SHA=${GIT_SHA}

# Where file_write may write — a mounted volume, not the image, so agent writes
# survive a rebuild and cannot modify the code they are running from. compose
# overrides this to /data; the default keeps a plain `docker run` usable.
ENV ALLOWED_WRITE_ROOT=/data
RUN mkdir -p /data /app/logs

# Liveness by heartbeat age, not by process name.
#
# python:3.13-slim has no `ps`, so `ps aux | grep main.py` could never pass and
# the container would report unhealthy forever. main.py touches this file on
# every poll iteration (2s); a hung Supabase call stops touching it, which is
# the failure a process-name check cannot see anyway. start-period is generous
# because the startup banner makes several real network calls.
HEALTHCHECK --interval=60s --timeout=5s --start-period=120s --retries=3 \
    CMD python -c "import os,sys,time; p=os.environ.get('WORKER_HEARTBEAT_FILE','/tmp/sunday-worker.alive'); sys.exit(0 if os.path.exists(p) and time.time()-os.path.getmtime(p) < 180 else 1)"

# Runs as root on purpose. The Google token files are bind mounts that the
# worker rewrites in place when it refreshes them (google_auth.py), and on
# Docker Desktop for Windows those mounts are owned by root. A non-root user
# here would fail the first token refresh and silently lose Google access,
# which is a worse outcome than an unprivileged-process nicety in a
# single-tenant container on the owner's own laptop.
CMD ["python", "main.py"]
