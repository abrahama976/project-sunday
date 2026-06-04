import json
from supabase import Client
from datetime import datetime, timezone

async def task_list(client: Client, user_id: str, **kwargs) -> str:
    args = kwargs
    status_filter = args.get("status")
    query = (
        client.table("tasks")
        .select("id, title, status, priority, due_date, category, is_archived")
        .eq("user_id", user_id)
        .eq("is_archived", False)
        .order("created_at", desc=True)
        .limit(50)
    )
    if status_filter:
        query = query.eq("status", status_filter)
    result = query.execute()
    if not result.data:
        return "No tasks found."
    priority_label = {1: "low", 2: "normal", 3: "high"}
    lines = []
    for t in result.data:
        due = f" (due {t['due_date']})" if t.get("due_date") else ""
        pri = priority_label.get(t.get("priority", 2), "normal")
        cat = f" [{t['category']}]" if t.get("category") else ""
        lines.append(f"[{t['status'].upper()}][{pri}]{cat} {t['title']}{due} — id:{t['id'][:8]}")
    return "\n".join(lines)

async def task_create(client: Client, user_id: str, **kwargs) -> str:
    args = kwargs
    title = args.get("title", "").strip()
    if not title:
        return "Error: title is required."
    priority_map = {"low": 1, "normal": 2, "high": 3}
    priority_raw = args.get("priority", "normal")
    priority_int = priority_map.get(str(priority_raw).lower(), 2) if isinstance(priority_raw, str) else int(priority_raw)
    row = {
        "user_id": user_id,
        "title": title,
        "status": "open",
        "priority": priority_int,
        "due_date": args.get("due_date"),
        "category": args.get("category"),
        "description": args.get("description"),
        "is_archived": False,
        "flexibility_score": 0,
    }
    result = client.table("tasks").insert(row).execute()
    if not result.data:
        return "Error: failed to create task."
    return f"Task created: \"{title}\" (id:{result.data[0]['id'][:8]})"

async def task_update(client: Client, user_id: str, **kwargs) -> str:
    args = kwargs
    task_id = args.get("id", args.get("task_id", "")).strip()
    if not task_id:
        return "Error: task id is required."
    allowed = ("status", "title", "due_date", "category", "description", "is_archived")
    updates = {k: v for k, v in args.items() if k in allowed and v is not None}
    # Convert priority string to int if provided
    if "priority" in args and args["priority"] is not None:
        priority_map = {"low": 1, "normal": 2, "high": 3}
        p = args["priority"]
        updates["priority"] = priority_map.get(str(p).lower(), 2) if isinstance(p, str) else int(p)
    # Set completed_at when marking done
    if updates.get("status") == "done":
        updates["completed_at"] = datetime.now(timezone.utc).isoformat()
    if not updates:
        return "Error: no valid fields to update."
    result = (
        client.table("tasks")
        .update(updates)
        .eq("id", task_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not result.data:
        return f"Error: task {task_id[:8]} not found or not yours."
    return f"Task updated: {task_id[:8]} → {list(updates.keys())}"
