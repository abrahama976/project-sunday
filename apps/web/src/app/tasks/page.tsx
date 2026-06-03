"use client";

import { useEffect, useMemo, useState, useCallback } from "react";
import { createClient } from "@/lib/supabase/client";

type Task = {
  id: string;
  title: string;
  description: string | null;
  category: string | null;
  priority: number;
  status: string;
  due_date: string | null;
  created_at: string;
  completed_at: string | null;
};

const PRIORITY_COLORS: Record<number, string> = {
  1: "var(--color-danger)",
  2: "var(--color-warning)",
  3: "transparent",
  4: "transparent",
  5: "transparent",
};

const STATUS_ICONS: Record<string, string> = {
  open: "○",
  in_progress: "◐",
  done: "●",
  cancelled: "✗",
};

const FILTERS = ["open", "all", "done"] as const;

/* ── Add Task Modal ────────────────────────────────────────── */
function AddTaskForm({ onSubmit, onCancel }: {
  onSubmit: (title: string, category: string, priority: number, dueDate: string) => void;
  onCancel: () => void;
}) {
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState("personal");
  const [priority, setPriority] = useState(3);
  const [dueDate, setDueDate] = useState("");

  return (
    <div style={{
      background: "var(--color-surface)",
      border: "1px solid var(--color-border)",
      borderRadius: "var(--radius-lg)",
      padding: "var(--space-5)",
      marginBottom: "var(--space-4)",
    }}>
      <input
        type="text"
        placeholder="Task title…"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        autoFocus
        onKeyDown={(e) => {
          if (e.key === "Enter" && title.trim()) {
            onSubmit(title.trim(), category, priority, dueDate);
          }
          if (e.key === "Escape") onCancel();
        }}
        style={{
          width: "100%",
          background: "var(--color-surface-2)",
          border: "1px solid var(--color-border)",
          borderRadius: "var(--radius-md)",
          padding: "var(--space-3) var(--space-4)",
          fontSize: "0.9375rem",
          color: "var(--color-text)",
          outline: "none",
          marginBottom: "var(--space-3)",
        }}
      />
      <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap", alignItems: "center" }}>
        <select
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          style={selectStyle}
        >
          <option value="personal">Personal</option>
          <option value="work">Work</option>
          <option value="health">Health</option>
          <option value="finance">Finance</option>
          <option value="project">Project</option>
        </select>
        <select
          value={priority}
          onChange={(e) => setPriority(Number(e.target.value))}
          style={selectStyle}
        >
          <option value={1}>P1 Urgent</option>
          <option value={2}>P2 High</option>
          <option value={3}>P3 Normal</option>
          <option value={4}>P4 Low</option>
          <option value={5}>P5 Someday</option>
        </select>
        <input
          type="date"
          value={dueDate}
          onChange={(e) => setDueDate(e.target.value)}
          style={{ ...selectStyle, minWidth: 130 }}
        />
        <div style={{ flex: 1 }} />
        <button onClick={onCancel} style={cancelBtnStyle}>Cancel</button>
        <button
          onClick={() => { if (title.trim()) onSubmit(title.trim(), category, priority, dueDate); }}
          disabled={!title.trim()}
          style={{
            ...primaryBtnStyle,
            opacity: title.trim() ? 1 : 0.4,
            cursor: title.trim() ? "pointer" : "not-allowed",
          }}
        >Add</button>
      </div>
    </div>
  );
}

/* ── Task Row ──────────────────────────────────────────────── */
function TaskRow({ task, onToggle }: { task: Task; onToggle: (id: string, done: boolean) => void }) {
  const isDone = task.status === "done" || task.status === "cancelled";

  return (
    <div style={{
      display: "flex",
      alignItems: "flex-start",
      gap: "var(--space-3)",
      padding: "var(--space-3) var(--space-4)",
      borderLeft: `3px solid ${PRIORITY_COLORS[task.priority] ?? "transparent"}`,
      background: "var(--color-surface)",
      border: "1px solid var(--color-border)",
      borderLeftWidth: 3,
      borderLeftColor: PRIORITY_COLORS[task.priority] ?? "transparent",
      borderRadius: "var(--radius-md)",
      opacity: isDone ? 0.5 : 1,
      transition: "opacity 200ms",
    }}>
      {/* Checkbox */}
      <button
        onClick={() => onToggle(task.id, !isDone)}
        aria-label={isDone ? "Mark as open" : "Mark as done"}
        style={{
          width: 20, height: 20,
          borderRadius: "var(--radius-sm)",
          border: isDone ? "none" : "2px solid var(--color-border-strong)",
          background: isDone ? "var(--color-success)" : "transparent",
          color: "#fff",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          cursor: "pointer",
          flexShrink: 0,
          marginTop: 2,
          fontSize: "0.75rem",
          transition: "background 150ms",
        }}
      >
        {isDone && "✓"}
      </button>

      {/* Content */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontSize: "0.9375rem",
          fontWeight: 450,
          textDecoration: isDone ? "line-through" : "none",
          color: isDone ? "var(--color-text-faint)" : "var(--color-text)",
        }}>
          {task.title}
        </div>
        <div style={{
          display: "flex",
          gap: "var(--space-2)",
          marginTop: "var(--space-1)",
          flexWrap: "wrap",
        }}>
          {task.category && (
            <span style={tagStyle}>{task.category}</span>
          )}
          {task.due_date && (
            <span style={{
              ...tagStyle,
              color: isOverdue(task.due_date) && !isDone ? "var(--color-danger)" : "var(--color-text-faint)",
            }}>
              {formatDue(task.due_date)}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Helpers ───────────────────────────────────────────────── */
function isOverdue(dateStr: string): boolean {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return new Date(dateStr) < today;
}

function formatDue(dateStr: string): string {
  const d = new Date(dateStr + "T00:00:00");
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diff = Math.round((d.getTime() - today.getTime()) / (86400 * 1000));
  if (diff === 0) return "Today";
  if (diff === 1) return "Tomorrow";
  if (diff === -1) return "Yesterday";
  if (diff < 0) return `${Math.abs(diff)}d overdue`;
  if (diff < 7) return d.toLocaleDateString("en-AU", { weekday: "short" });
  return d.toLocaleDateString("en-AU", { day: "numeric", month: "short" });
}

/* ── Main Page ─────────────────────────────────────────────── */
export default function TasksPage() {
  const supabase = useMemo(() => createClient(), []);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("open");
  const [showAdd, setShowAdd] = useState(false);

  const fetchTasks = useCallback(async () => {
    let query = supabase.from("tasks").select("*");

    if (filter === "open") {
      query = query.in("status", ["open", "in_progress"]);
    } else if (filter === "done") {
      query = query.in("status", ["done", "cancelled"]);
    }

    query = query.order("priority", { ascending: true }).order("due_date", { ascending: true, nullsFirst: false });
    const { data } = await query.limit(100);
    setTasks((data || []) as Task[]);
    setLoading(false);
  }, [supabase, filter]);

  useEffect(() => {
    void fetchTasks();
  }, [fetchTasks]);

  // Realtime subscription for task changes
  useEffect(() => {
    const channel = supabase
      .channel("tasks-realtime")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "tasks" },
        () => { void fetchTasks(); }
      )
      .subscribe();

    return () => { supabase.removeChannel(channel); };
  }, [supabase, fetchTasks]);

  const handleToggle = async (id: string, markDone: boolean) => {
    const update: Record<string, unknown> = {
      status: markDone ? "done" : "open",
    };
    if (markDone) {
      update.completed_at = new Date().toISOString();
    } else {
      update.completed_at = null;
    }

    // Optimistic update
    setTasks((prev) => prev.map((t) =>
      t.id === id ? { ...t, status: markDone ? "done" : "open", completed_at: markDone ? new Date().toISOString() : null } : t
    ));

    await supabase.from("tasks").update(update).eq("id", id);
  };

  const handleAdd = async (title: string, category: string, priority: number, dueDate: string) => {
    const row: Record<string, unknown> = {
      title,
      category,
      priority,
      status: "open",
      source: "manual",
    };
    if (dueDate) row.due_date = dueDate;

    await supabase.from("tasks").insert(row);
    setShowAdd(false);
    void fetchTasks();
  };

  const openCount = tasks.filter((t) => t.status === "open" || t.status === "in_progress").length;

  return (
    <div style={{ maxWidth: "800px", margin: "0 auto", padding: "var(--space-6) var(--space-5)" }}>
      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        marginBottom: "var(--space-5)",
      }}>
        <div>
          <h1 style={{ fontSize: "1.125rem", fontWeight: 600, marginBottom: "var(--space-1)" }}>
            Tasks
          </h1>
          <p style={{ fontSize: "0.75rem", color: "var(--color-text-faint)" }}>
            {openCount} open
          </p>
        </div>
        <button
          onClick={() => setShowAdd(true)}
          style={{
            width: 36, height: 36,
            borderRadius: "var(--radius-md)",
            background: "var(--color-primary)",
            color: "#fff",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: "1.125rem",
            fontWeight: 300,
            cursor: "pointer",
            border: "none",
            transition: "opacity 150ms",
          }}
          aria-label="Add task"
        >+</button>
      </div>

      {/* Filters */}
      <div style={{
        display: "flex", gap: "var(--space-1)",
        marginBottom: "var(--space-4)",
      }}>
        {FILTERS.map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            style={{
              padding: "var(--space-2) var(--space-4)",
              borderRadius: "9999px",
              border: "1px solid var(--color-border)",
              background: filter === f ? "var(--color-primary-faint)" : "transparent",
              color: filter === f ? "var(--color-primary)" : "var(--color-text-muted)",
              fontSize: "0.75rem",
              fontWeight: filter === f ? 600 : 400,
              cursor: "pointer",
              textTransform: "capitalize",
              transition: "all 150ms",
            }}
          >{f}</button>
        ))}
      </div>

      {/* Add form */}
      {showAdd && (
        <AddTaskForm onSubmit={handleAdd} onCancel={() => setShowAdd(false)} />
      )}

      {/* Task list */}
      {loading ? (
        <p style={{ color: "var(--color-text-faint)", fontSize: "0.8125rem" }}>Loading…</p>
      ) : tasks.length === 0 ? (
        <div style={{
          padding: "var(--space-8)", textAlign: "center",
          borderRadius: "var(--radius-lg)",
          border: "1px dashed var(--color-border)",
          color: "var(--color-text-faint)", fontSize: "0.8125rem",
        }}>
          {filter === "open" ? "No open tasks. Add one above or tell Sunday in chat." : "No tasks found."}
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
          {tasks.map((task) => (
            <TaskRow key={task.id} task={task} onToggle={handleToggle} />
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Shared styles ─────────────────────────────────────────── */
const selectStyle: React.CSSProperties = {
  background: "var(--color-surface-2)",
  border: "1px solid var(--color-border)",
  borderRadius: "var(--radius-md)",
  padding: "var(--space-2) var(--space-3)",
  fontSize: "0.75rem",
  color: "var(--color-text)",
  outline: "none",
};

const tagStyle: React.CSSProperties = {
  fontSize: "0.6875rem",
  color: "var(--color-text-faint)",
  letterSpacing: "0.02em",
};

const cancelBtnStyle: React.CSSProperties = {
  padding: "var(--space-2) var(--space-4)",
  borderRadius: "var(--radius-md)",
  border: "1px solid var(--color-border)",
  background: "transparent",
  fontSize: "0.8125rem",
  color: "var(--color-text-muted)",
  cursor: "pointer",
};

const primaryBtnStyle: React.CSSProperties = {
  padding: "var(--space-2) var(--space-5)",
  borderRadius: "var(--radius-md)",
  border: "none",
  background: "var(--color-primary)",
  fontSize: "0.8125rem",
  fontWeight: 500,
  color: "#fff",
  cursor: "pointer",
  transition: "opacity 150ms",
};
