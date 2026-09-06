"""What commit this worker is actually running.

Read once at import from the checkout the worker was started from.

This exists because of an hour spent on the wrong question. Four fixes were
merged and the answers in chat did not change; the natural reading was that the
fixes were wrong. They were not running. The worker was still on an older
commit, and nothing anywhere — not the heartbeat, not the startup banner, not
the traces — could say so. The evidence had to be reconstructed backwards from
model behaviour: a 2024 date the new prompt would have prevented, a past time
the new guard would have refused, a 500 km destination the new gate would have
rejected.

`git rev-parse` rather than a version constant someone has to remember to bump:
the one number that cannot drift from what is on disk is the one read from what
is on disk.
"""
import os
import subprocess

_WORKER_DIR = os.path.dirname(os.path.abspath(__file__))


def _git(*args) -> str:
    """A git command in the worker's own checkout, or "" if it cannot run.

    Never raises and never blocks for long: a worker must start on a machine
    with no git, or a checkout that is not a repository, exactly as it does now.
    """
    try:
        out = subprocess.run(
            ("git", "-C", _WORKER_DIR) + args,
            capture_output=True, text=True, timeout=5.0,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout.strip() if out.returncode == 0 else ""


def _read_version() -> str:
    # A container has no .git, so the sha has to be stamped in at build time or
    # this reports "unknown" forever — which would quietly undo the whole point
    # of the version stamp for anything not run from a checkout.
    #
    # It is trusted, and it can lie: whatever sets it asserts what is running.
    # That is fine when a build stamps it from the commit it built, and it is
    # why the git read below stays the default rather than the fallback of last
    # resort — a checkout still reports what is actually there, `+dirty` and all.
    env_sha = os.getenv("GIT_SHA")
    if env_sha:
        return env_sha.strip()

    sha = _git("rev-parse", "--short", "HEAD")
    if not sha:
        return "unknown"
    # A dirty tree is worth knowing about: it means the running code is not any
    # commit, so comparing the sha against a merged PR proves nothing.
    #
    # Tracked files only. The first run reported `160c450+dirty` because of one
    # untracked scratch file, which says nothing about whether the code matches
    # the commit — and a flag that cries wolf gets ignored, which would defeat
    # the point of adding it. This is what `git describe --dirty` counts too.
    dirty = "+dirty" if _git("status", "--porcelain", "--untracked-files=no") else ""
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    branch = "" if branch in ("", "HEAD") else f" ({branch})"
    return f"{sha}{dirty}{branch}"


# Read once. The running process does not change commit underneath itself, and
# a restart is what picks up a new one — which is the whole point.
VERSION = _read_version()
