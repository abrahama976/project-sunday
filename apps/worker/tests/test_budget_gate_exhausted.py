import asyncio
from unittest.mock import MagicMock, patch
from budget_gate import pick_model
async def _test():
    mock_client = MagicMock()
    async def fake_get_usage(client, user_id, tier):
        return 9999
    with patch("budget_gate.get_usage", side_effect=fake_get_usage), \
         patch("budget_gate._probe_ollama", return_value=False):
        result = await pick_model(mock_client, "any-user-id")
    assert result == "EXHAUSTED", f"Expected EXHAUSTED, got {result!r}"
    print("✓ EXHAUSTED sentinel fires correctly")
if __name__ == "__main__":
    asyncio.run(_test())
