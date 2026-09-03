"""Every tier is over its cap, so pick_model returns the EXHAUSTED sentinel.

Pure: the Supabase client is a MagicMock and every provider probe is patched
out. It just needed the harness to be importable at all — without it, `import
budget_gate` fails on httpx and the file cannot run in a bare checkout.
"""
import asyncio
from unittest.mock import MagicMock, patch

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import setup; setup()

from budget_gate import pick_model
async def _test():
    mock_client = MagicMock()
    async def fake_get_usage(client, user_id, tier):
        return 9999
    with patch("budget_gate.get_usage", side_effect=fake_get_usage), \
         patch("budget_gate._probe_ollama", return_value=False), \
         patch("budget_gate._groq_available", return_value=False):
        result = await pick_model(mock_client, "any-user-id")
    assert result == "EXHAUSTED", f"Expected EXHAUSTED, got {result!r}"
    print("✓ EXHAUSTED sentinel fires correctly")
if __name__ == "__main__":
    asyncio.run(_test())
