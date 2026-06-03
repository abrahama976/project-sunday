"""Task management executors: create, update, list.

Tasks are stored in the Supabase `tasks` table and managed
entirely through these executors. The AI can create tasks from
conversation, and the user can view/manage them in the Tasks screen.
"""
import json
from datetime import date
from supabase import Client


async def task_create(
    client: Client,
    title: str,
    category: str = "personal",
    priority: int = 3,
    due_date: str = "",
    description: str = "",
    source: str = "chat",
    source_message_id: str = "",
) -> str:
    """Create a new task."""
    row: dict = {
        "title": title,
        "category": category,
        "priority": max(1, min(priority, 5)),
        "status": "open",
        "source": source,
    }
    if due_date:
        row["due_date"] = due_date
    if description:
        row["description"] = description
    if source_message_id:
        row["source_message_id"] = source_message_id

    result = client.table("tasks").insert(row).execute()
    if result.data:
        return f"Task created: '{title}' (priority {priority}, category: {category})"
    return f"Failed to create task: '{title}'"


async def task_update(
    client: Client,
    task_id: str,
    title: str = "",
    status: str = "",
    priority: int = 0,
    due_date: str = "",
    category: str = "",
    description: str = "",
) -> str:
    """Update an existing task's fields."""
    update: dict = {}
    if title:
        update["title"] = title
    if status and status in ("open", "in_progress", "done", "cancelled"):
        update["status"] = status
        if status == "done":
            from datetime import datetime, timezone
            update["completed_at"] = datetime.now(timezone.utc).isoformat()
    if priority:
        update["priority"] = max(1, min(priority, 5))
    if due_date:
        update["due_date"] = due_date
    if category:
        update["category"] = category
    if description:
        update["description"] = description

    if not update:
        return "No fields to update."

    result = (
        client.table("tasks")
        .update(update)
        .eq("id", task_id)
        .execute()
    )

    if result.data:
        task_title = result.data[0].get("title", task_id)
        return f"Task updated: '{task_title}'"
    return f"Task not found: {task_id}"


async def task_list(
    client: Client,
    status: str = "open",
    category: str = "",
    due_before: str = "",
    limit: int = 20,
) -> str:
    """List tasks filtered by status, category, and due date."""
    query = client.table("tasks").select("*")

    if status and status != "all":
        query = query.eq("status", status)
    if category:
        query = query.eq("category", category)
    if due_before:
        query = query.lte("due_date", due_before)

    query = query.order("priority", desc=False).order("due_date", desc=False)
    result = query.limit(min(limit, 50)).execute()

    tasks = result.data or []
    if not tasks:
        filters = []
        if status and status != "all":
            filters.append(f"status={status}")
        if category:
            filters.append(f"category={category}")
        filter_str = f" ({', '.join(filters)})" if filters else ""
        return f"No tasks found{filter_str}."

    lines = []
    for t in tasks:
        p = t.get("priority", 3)
        prefix = "!" * min(p, 3) if p <= 2 else ""
        due = f" (due {t['due_date']})" if t.get("due_date") else ""
        cat = f" [{t['category']}]" if t.get("category") else ""
        status_icon = {"open": "○", "in_progress": "◐", "done": "●", "cancelled": "✗"}.get(
            t.get("status", "open"), "○"
        )
        lines.append(f"{status_icon} {prefix}{t['title']}{cat}{due}")

    header = f"{len(tasks)} task(s):"
    return f"{header}\n" + "\n".join(lines)
