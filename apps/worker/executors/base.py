import asyncio
from datetime import datetime, timezone

from supabase import Client

# Statuses that mean the action is over, one way or the other. These are the
# only ones that get a timestamp: `processing` is a status the row passes
# through, and stamping it would make "when did this run" mean "when did it
# last change", which is a different and much less useful question.
_TERMINAL = frozenset({"executed", "failed", "denied"})


async def set_status(client: Client, action_id: str, status: str, error: dict = None):
    """Move a queued action to `status`, stamping when it finished.

    `executed_at` has been in the schema and on the approvals page since the
    queue was built, and nothing ever wrote it — so every executed action has
    rendered with no time against it. The column was not wrong; the writer was
    missing.
    """
    update = {"status": status}
    if error:
        update["error"] = error
    if status in _TERMINAL:
        update["executed_at"] = datetime.now(timezone.utc).isoformat()
    await asyncio.to_thread(lambda: client.table("action_queue").update(update).eq("id", action_id).execute())
