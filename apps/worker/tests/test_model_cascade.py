"""The model cascade: order, the NVIDIA tier, and an unset key.

Pure: no network, no database. The ledger is a dict and the Ollama probe is a
flag, so the whole ladder can be walked in a few milliseconds — which is the
only way to assert an order that would otherwise cost real requests to observe.

Why this exists: every ID in the old cascade was retired (2.0 shut down 1 Jun
2026, 2.5 Pro off the free tier 1 Apr 2026), and a dead ID does not raise at
import time — it fails at the end of a user's turn, five rounds deep. The
cascade is now checked mechanically, including that a provider this machine has
no key for is skipped rather than attempted.
"""
import asyncio
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test")
os.environ.setdefault("GEMINI_API_KEY", "test")

import budget_gate  # noqa: E402
from budget_gate import (  # noqa: E402
    pick_model, _model_to_tier,
    TIER_FLASH, TIER_LITE, TIER_NVIDIA, TIER_GROQ,
    DAILY_FLASH_LIMIT, DAILY_LITE_LIMIT, DAILY_NVIDIA_LIMIT,
)
from config import (  # noqa: E402
    GEMINI_MODEL, GEMINI_LITE_MODEL, GROQ_MODEL, NVIDIA_MODEL, NVIDIA_RPM_LIMIT,
)

failures = []


def check(label, actual, expected):
    if actual != expected:
        failures.append(f"{label}\n     expected: {expected!r}\n     actual:   {actual!r}")
    else:
        print(f"  ok  {label}")


def check_true(label, cond, detail=""):
    if cond:
        print(f"  ok  {label}")
    else:
        failures.append(f"{label} {detail}")
        print(f"  ✗   {label} {detail}")


# ── Fakes ──────────────────────────────────────────────────────────────────

USAGE: dict[str, int] = {}
OLLAMA_UP = {"value": True}
CLIENT = object()          # pick_model never touches it through a fake


async def fake_get_usage(client, user_id, tier):
    return USAGE.get(tier, 0)


async def fake_probe_ollama():
    return OLLAMA_UP["value"]


budget_gate.get_usage = fake_get_usage
budget_gate._probe_ollama = fake_probe_ollama


def reset(flash=0, lite=0, nvidia=0, groq_key="", nvidia_key="key", ollama=True):
    USAGE.clear()
    USAGE[TIER_FLASH] = flash
    USAGE[TIER_LITE] = lite
    USAGE[TIER_NVIDIA] = nvidia
    budget_gate.GROQ_API_KEY = groq_key
    budget_gate.NVIDIA_API_KEY = nvidia_key
    budget_gate._reset_nvidia_rpm()
    OLLAMA_UP["value"] = ollama


async def pick():
    return await pick_model(CLIENT, "user-a")


async def run():
    print("── the ladder, in order ────────────────────────────────")
    reset()
    check("everything available → Gemini Flash", await pick(), GEMINI_MODEL)

    reset(flash=DAILY_FLASH_LIMIT)
    check("Flash spent → Flash-Lite", await pick(), GEMINI_LITE_MODEL)

    reset(flash=DAILY_FLASH_LIMIT, lite=DAILY_LITE_LIMIT, groq_key="g")
    check("both Gemini tiers spent → NVIDIA", await pick(), NVIDIA_MODEL)

    reset(flash=DAILY_FLASH_LIMIT, lite=DAILY_LITE_LIMIT, nvidia=DAILY_NVIDIA_LIMIT, groq_key="g")
    check("NVIDIA at its daily cap → Groq", await pick(), GROQ_MODEL)

    reset(flash=DAILY_FLASH_LIMIT, lite=DAILY_LITE_LIMIT, nvidia=DAILY_NVIDIA_LIMIT)
    check("no Groq key → Ollama", await pick(), "ollama")

    reset(flash=DAILY_FLASH_LIMIT, lite=DAILY_LITE_LIMIT, nvidia=DAILY_NVIDIA_LIMIT, ollama=False)
    check("nothing left → EXHAUSTED", await pick(), "EXHAUSTED")

    print("\n── an unset NVIDIA key skips the tier, not the turn ──")
    reset(flash=DAILY_FLASH_LIMIT, lite=DAILY_LITE_LIMIT, nvidia_key="", groq_key="g")
    check("no NVIDIA key → straight to Groq", await pick(), GROQ_MODEL)

    reset(flash=DAILY_FLASH_LIMIT, lite=DAILY_LITE_LIMIT, nvidia_key="", ollama=False)
    check("no NVIDIA key and no Groq → EXHAUSTED, not NVIDIA", await pick(), "EXHAUSTED")

    print("\n── the per-minute guard ───────────────────────────────")
    reset(flash=DAILY_FLASH_LIMIT, lite=DAILY_LITE_LIMIT, groq_key="g")
    now = time.monotonic()
    for i in range(NVIDIA_RPM_LIMIT):
        budget_gate._note_nvidia_call(now=now - 1 + i * 0.001)
    check("a full minute of NVIDIA calls falls through to Groq", await pick(), GROQ_MODEL)
    check_true("...and the guard says the window is full",
               not budget_gate._nvidia_rpm_ok(now=now + 1))
    check_true("...and is open again a minute later",
               budget_gate._nvidia_rpm_ok(now=now + 62))

    budget_gate._reset_nvidia_rpm()
    budget_gate._note_nvidia_call(now=now)
    check("one call does not close the window",
           await pick(), NVIDIA_MODEL)

    print("\n── ledger tiers, including the llama-name trap ────────")
    check("Gemini Flash is its own tier", _model_to_tier(GEMINI_MODEL), TIER_FLASH)
    check("Gemini Flash-Lite is its own tier", _model_to_tier(GEMINI_LITE_MODEL), TIER_LITE)
    check("the NVIDIA model is NOT filed as Groq", _model_to_tier(NVIDIA_MODEL), TIER_NVIDIA)
    check("...even though its name contains 'llama'", "llama" in NVIDIA_MODEL.lower(), True)
    check("Groq is Groq", _model_to_tier(GROQ_MODEL), TIER_GROQ)
    check("a bare provider-qualified id is NVIDIA", _model_to_tier("meta/some-model"), TIER_NVIDIA)

    print("\n── every model id is overridable from the environment ─")
    overrides = {
        "GEMINI_MODEL": "gemini-test-flash",
        "GEMINI_LITE_MODEL": "gemini-test-lite",
        "NVIDIA_MODEL": "vendor/test-model",
        "GROQ_MODEL": "test-groq-model",
        "OLLAMA_MODEL": "test-ollama",
        "OLLAMA_HOST": "http://laptop.local:11434",
    }
    env = dict(os.environ, **overrides)
    code = (
        "import config;"
        "print(config.GEMINI_MODEL, config.GEMINI_LITE_MODEL, config.NVIDIA_MODEL,"
        "config.GROQ_MODEL, config.OLLAMA_MODEL, config.OLLAMA_HOST)"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        cwd=os.path.join(os.path.dirname(__file__), ".."),
        env=env, capture_output=True, text=True,
    )
    check("config honours all six variables", out.stdout.strip().split(),
          [overrides[k] for k in overrides])
    check_true("...and exits cleanly", out.returncode == 0, out.stderr[-300:])

    print()
    if failures:
        print(f"✗ {len(failures)} failure(s):\n")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("✓ all model cascade tests passed")


asyncio.run(run())
