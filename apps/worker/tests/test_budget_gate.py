"""Phase 5 Step 1 — Budget Gate Acceptance Tests.

Acceptance criteria:
(a) No LLM call path bypasses the gate  → verified by grep (separate command)
(b) A user at their Flash cap is transparently served by Lite/Ollama
(c) Concurrent increments don't double-count (atomic test)

Note: Uses a real user_id from user_profile to satisfy FK constraints.

NOT a pure test, and deliberately not on the `_harness` stubs: it writes real
rows to `usage_counters` to prove the increment is atomic, which is the one
thing a fake cannot demonstrate. It needs the dependencies installed and a live
SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY, so it does not run in a bare
checkout. Run it on the Mac, against the real project, when budget_gate
changes.
"""
import asyncio
import sys
import os
from datetime import date

# Ensure worker modules are importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from budget_gate import pick_model, check_and_increment, get_usage, TIER_FLASH, TIER_LITE
from config import DAILY_FLASH_LIMIT, DAILY_LITE_LIMIT, GEMINI_MODEL, GEMINI_LITE_MODEL, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
from supabase import create_client


async def run_tests():
    client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

    # Get a real user_id from the system (satisfies FK on auth.users)
    user_res = await asyncio.to_thread(
        lambda: client.table("user_profile").select("user_id").limit(1).maybe_single().execute()
    )
    if not user_res.data or not user_res.data.get("user_id"):
        print("ERROR: No user found in user_profile — cannot test FK-constrained table.")
        sys.exit(1)

    test_uid = user_res.data["user_id"]
    today = date.today().isoformat()
    print(f"Test user_id: {test_uid}")
    print(f"Date: {today}")
    print(f"Flash limit: {DAILY_FLASH_LIMIT}, Lite limit: {DAILY_LITE_LIMIT}")
    print()

    # ─── Save original usage to restore later ───
    original_flash = await get_usage(client, test_uid, TIER_FLASH)
    original_lite = await get_usage(client, test_uid, TIER_LITE)
    print(f"Original usage — Flash: {original_flash}, Lite: {original_lite}")

    # ─────────────────────────────────────────────
    # TEST (b): Cap overflow cascades correctly
    # ─────────────────────────────────────────────
    print()
    print("=" * 60)
    print("TEST (b): Cap overflow → model cascade")
    print("=" * 60)

    # 1. If user already at Flash limit, skip to next tier; otherwise test fresh
    if original_flash < DAILY_FLASH_LIMIT:
        model = await pick_model(client, test_uid)
        assert model == GEMINI_MODEL, f"Expected Flash, got {model}"
        print(f"  [PASS] User below Flash limit → {model} (Flash)")

    # 2. Artificially set Flash to the limit using the RPC in a loop
    #    We'll increment up to the limit
    need_flash = DAILY_FLASH_LIMIT - original_flash
    for _ in range(need_flash):
        await asyncio.to_thread(
            lambda: client.rpc("increment_llm_usage", {
                "p_user_id": test_uid,
                "p_date": today,
                "p_model": "flash",
            }).execute()
        )
    
    flash_now = await get_usage(client, test_uid, TIER_FLASH)
    assert flash_now >= DAILY_FLASH_LIMIT, f"Flash should be at limit, got {flash_now}"
    print(f"  [OK] Flash usage set to {flash_now}")

    model = await pick_model(client, test_uid)
    assert model == GEMINI_LITE_MODEL, f"Expected Lite, got {model}"
    print(f"  [PASS] Flash exhausted → {model} (Lite)")

    # 3. Artificially set Lite to the limit
    need_lite = DAILY_LITE_LIMIT - original_lite
    for _ in range(need_lite):
        await asyncio.to_thread(
            lambda: client.rpc("increment_llm_usage", {
                "p_user_id": test_uid,
                "p_date": today,
                "p_model": "lite",
            }).execute()
        )

    lite_now = await get_usage(client, test_uid, TIER_LITE)
    assert lite_now >= DAILY_LITE_LIMIT, f"Lite should be at limit, got {lite_now}"
    print(f"  [OK] Lite usage set to {lite_now}")

    model = await pick_model(client, test_uid)
    assert model == "ollama", f"Expected ollama, got {model}"
    print(f"  [PASS] Both tiers exhausted → {model} (Ollama)")

    # ─── Restore original usage ───
    # Reset flash and lite back to original values
    await asyncio.to_thread(
        lambda: client.table("user_llm_ledger")
        .update({"request_count": original_flash})
        .eq("user_id", test_uid)
        .eq("ledger_date", today)
        .eq("model", "flash")
        .execute()
    )
    await asyncio.to_thread(
        lambda: client.table("user_llm_ledger")
        .update({"request_count": original_lite})
        .eq("user_id", test_uid)
        .eq("ledger_date", today)
        .eq("model", "lite")
        .execute()
    )
    print("  [CLEANUP] Restored original usage counts.")
    print()

    # ─────────────────────────────────────────────
    # TEST (c): Concurrent increments are atomic
    # ─────────────────────────────────────────────
    print("=" * 60)
    print("TEST (c): Concurrent atomic increments")
    print("=" * 60)

    # Record current flash usage before the test
    before = await get_usage(client, test_uid, TIER_FLASH)
    N = 10

    # Fire N concurrent check_and_increment calls
    results = await asyncio.gather(*[
        check_and_increment(client, test_uid, GEMINI_MODEL) for _ in range(N)
    ])

    # All should return True (well within budget since we restored)
    assert all(results), f"Some increments were rejected: {results}"
    print(f"  [PASS] All {N} concurrent increments returned True")

    # Verify the ledger increased by exactly N
    after = await get_usage(client, test_uid, TIER_FLASH)
    delta = after - before
    assert delta == N, f"Expected delta of {N}, got {delta} (before={before}, after={after})"
    print(f"  [PASS] Ledger delta = {delta} (expected {N}) — no double-count")

    # Restore original value
    await asyncio.to_thread(
        lambda: client.table("user_llm_ledger")
        .update({"request_count": original_flash})
        .eq("user_id", test_uid)
        .eq("ledger_date", today)
        .eq("model", "flash")
        .execute()
    )
    print("  [CLEANUP] Restored original Flash usage count.")
    print()

    print("=" * 60)
    print("ALL ACCEPTANCE TESTS PASSED ✅")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_tests())
