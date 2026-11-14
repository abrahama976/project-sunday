"use client";

import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import {
  type Task,
  isTask,
  PRIORITY_LABELS,
  PRIORITY_COLORS,
  priorityBadge,
  sortTasksByDueDate,
  parseTaskFilter,
  matchesTaskFilter,
} from "@/lib/tasks";

/**
 * "Active" is a product rule, not a type rule: an in-progress task is still
 * yours to do, a cancelled one is not. It lives in the query, where an
 * exclusion is visible, rather than in `isTask`, where it would be silent.
 */
const ACTIVE_STATUSES = ["open", "in_progress"];

function FilterChip({
  href,
  label,
  count,
  active,
  tone,
}: {
  href: string;
  label: string;
  count: number;
  active: boolean;
  tone?: "chip-danger" | "chip-warning";
}) {
  const className = active ? `chip ${tone ?? "chip-primary"}` : "chip";
  return (
    <Link
      href={href}
      className={className}
      style={{ textDecoration: "none" }}
      aria-current={active ? "page" : undefined}
    >
      {label} · {count}
    </Link>
  );
}

function TasksPageInner() {
  const supabase = useMemo(() => createClient(), []);
  const search = useSearchParams();
  const filter = parseTaskFilter(search.get("filter"));

  const [tasks, setTasks] = useState<Task[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Read by the polling fallback below, which closes over its initial value
  // and so cannot use state to decide whether Realtime is carrying updates.
  const liveRef = useRef(false);

  // Same clock as Today: ticking, so "late" cannot go stale overnight, and one
  // value shared by the chip counts and the filtered rows so they cannot
  // disagree. Safe to seed in an initialiser — the server render has no rows to
  // count, so nothing it produces depends on the hour.
  const [now, setNow] = useState<Date>(() => new Date());
  useEffect(() => {
    const every = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(every);
  }, []);

  useEffect(() => {
    let cancelled = false;
    let channel: ReturnType<typeof supabase.channel> | null = null;
    let pollInterval: number | undefined;

    const loadTasks = async () => {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user || cancelled) return;

      const { data, error: loadErr } = await supabase
        .from("tasks")
        .select("*")
        .eq("user_id", user.id)
        .in("status", ACTIVE_STATUSES)
        .eq("is_archived", false)
        .order("created_at", { ascending: false });

      if (cancelled) return;
      if (loadErr) {
        setError(`Failed to load tasks: ${loadErr.message}`);
        return;
      }
      if (data) {
        setTasks(data.filter(isTask));
      }
    };

    const { data: authListener } = supabase.auth.onAuthStateChange(
      (_event, session) => {
        if (session?.access_token) {
          supabase.realtime.setAuth(session.access_token);
        }
      }
    );

    void (async () => {
      const { data: { session } } = await supabase.auth.getSession();
      if (cancelled) return;
      if (session?.access_token) {
        await supabase.realtime.setAuth(session.access_token);
      }

      channel = supabase
        .channel("tasks-realtime")
        .on(
          "postgres_changes",
          { event: "*", schema: "public", table: "tasks" },
          () => {
            void loadTasks();
          }
        )
        .subscribe((status, err) => {
          if (cancelled) return;
          if (status === "SUBSCRIBED") {
            liveRef.current = true;
            void loadTasks();
          } else if (status === "CHANNEL_ERROR" || status === "TIMED_OUT") {
            liveRef.current = false;
            setError(`Realtime unavailable: ${err?.message ?? status}. Refresh to see updates.`);
            void loadTasks();
          }
        });

      // Only a fallback. Realtime already fires on every change to `tasks`, so
      // polling on top of it re-read the table every five seconds forever —
      // most of them against no tasks at all.
      pollInterval = setInterval(() => {
        if (liveRef.current) return;
        void loadTasks();
      }, 5000) as unknown as number;
    })();

    return () => {
      cancelled = true;
      clearInterval(pollInterval);
      authListener.subscription.unsubscribe();
      if (channel) supabase.removeChannel(channel);
    };
  }, [supabase]);

  const addTask = async () => {
    if (!input.trim() || loading) return;
    const text = input.trim();
    setInput("");
    setLoading(true);
    setError(null);

    try {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) throw new Error("Not authenticated");

      const { error: insertErr } = await supabase
        .from("tasks")
        .insert({
          user_id: user.id,
          title: text,
          priority: 2,
          status: "open",
          is_archived: false,
          flexibility_score: 0,
        });

      if (insertErr) throw insertErr;
    } catch (e) {
      setError(`Failed to create task: ${e instanceof Error ? e.message : "unknown error"}`);
    } finally {
      setLoading(false);
    }
  };

  const toggleTask = async (task: Task) => {
    try {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) throw new Error("Not authenticated");

      const newStatus = task.status === "open" ? "done" : "open";
      const completedAt = newStatus === "done" ? new Date().toISOString() : null;

      const { error: updateErr } = await supabase
        .from("tasks")
        .update({
          status: newStatus,
          completed_at: completedAt,
        })
        .eq("id", task.id)
        .eq("user_id", user.id);

      if (updateErr) throw updateErr;
    } catch (e) {
      setError(`Failed to update task: ${e instanceof Error ? e.message : "unknown error"}`);
    }
  };

  // Sorted once, then filtered — so the counts below are read off the same
  // rows the list shows, not off a second pass with its own rules.
  const active = useMemo(() => sortTasksByDueDate(tasks), [tasks]);
  const visible = useMemo(
    () => active.filter((t) => matchesTaskFilter(t, filter, now)),
    [active, filter, now]
  );
  const lateCount = useMemo(
    () => active.filter((t) => matchesTaskFilter(t, "late", now)).length,
    [active, now]
  );
  const todayCount = useMemo(
    () => active.filter((t) => matchesTaskFilter(t, "today", now)).length,
    [active, now]
  );

  const emptyMessage =
    filter === "late"
      ? "Nothing overdue."
      : filter === "today"
        ? "Nothing due today."
        : "No active tasks.";

  return (
    <div style={{
      display: "flex",
      flexDirection: "column",
      height: "calc(100dvh - var(--nav-top-h))",
      paddingBottom: "calc(var(--nav-bottom-h) + var(--safe-area-bottom))",
    }}>
      <div style={{
        flex: 1,
        overflowY: "auto",
        padding: "var(--space-4) var(--space-5)",
        display: "flex",
        flexDirection: "column",
        gap: "var(--space-2)",
      }}>
        <div className="row gap-2" style={{ flexWrap: "wrap", marginBottom: "var(--space-2)" }}>
          <FilterChip href="/tasks" label="All" count={active.length} active={filter === "all"} />
          <FilterChip
            href="/tasks?filter=late"
            label="Late"
            count={lateCount}
            active={filter === "late"}
            tone="chip-danger"
          />
          <FilterChip
            href="/tasks?filter=today"
            label="Due today"
            count={todayCount}
            active={filter === "today"}
            tone="chip-warning"
          />
        </div>

        {visible.length === 0 && !error && (
          <div style={{
            padding: "var(--space-8)", textAlign: "center",
            color: "var(--color-text-faint)", fontSize: "0.875rem",
          }}>
            {emptyMessage}
            {filter !== "all" && (
              <div style={{ marginTop: "var(--space-3)" }}>
                <Link href="/tasks" className="link-btn">Show all tasks</Link>
              </div>
            )}
          </div>
        )}

        {visible.map((task) => {
          const badge = priorityBadge(task.priority);
          return (
            <div
              key={task.id}
              style={{
                display: "flex",
                alignItems: "flex-start",
                gap: "var(--space-3)",
                padding: "var(--space-3)",
                background: "var(--color-surface-2)",
                borderRadius: "var(--radius-lg)",
                border: "1px solid var(--color-border)",
                opacity: task.status === "done" ? 0.6 : 1,
              }}
            >
              <button
                type="button"
                onClick={() => void toggleTask(task)}
                aria-label={task.status === "done" ? `Mark “${task.title}” not done` : `Mark “${task.title}” done`}
                aria-pressed={task.status === "done"}
                className="tap"
                style={{
                  padding: 0,
                  border: "none",
                  background: "none",
                  cursor: "pointer",
                  color: "var(--color-primary)",
                }}
              >
                <span
                  aria-hidden
                  style={{
                    width: 20,
                    height: 20,
                    borderRadius: "50%",
                    border: `2px solid ${task.status === "done" ? "var(--color-primary)" : "var(--color-border)"}`,
                    background: task.status === "done" ? "var(--color-primary)" : "transparent",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                  }}
                >
                  {task.status === "done" && (
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                      <polyline points="20 6 9 17 4 12" />
                    </svg>
                  )}
                </span>
              </button>

              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{
                  fontSize: "0.9375rem",
                  color: "var(--color-text)",
                  textDecoration: task.status === "done" ? "line-through" : "none",
                  wordBreak: "break-word",
                }}>
                  {task.title}
                </div>
                <div style={{
                  display: "flex",
                  gap: "var(--space-3)",
                  marginTop: "var(--space-1)",
                  fontSize: "0.75rem",
                  alignItems: "center",
                  flexWrap: "wrap",
                }}>
                  {/* 4 and 5 are carried by the badge, so the word "Priority" is
                      not repeated. 1–3 have no badge, so they need the text. */}
                  {task.priority <= 3 && (
                    <span style={{ color: PRIORITY_COLORS[task.priority] }}>
                      {PRIORITY_LABELS[task.priority]}
                    </span>
                  )}
                  {task.category && (
                    <span style={{ color: "var(--color-text-faint)" }}>
                      {task.category}
                    </span>
                  )}
                  {task.due_date && (
                    <span style={{ color: "var(--color-text-faint)" }}>
                      Due {task.due_date}
                    </span>
                  )}
                </div>
              </div>

              {badge && <span className={badge.className}>{badge.label}</span>}
            </div>
          );
        })}
      </div>

      {error && (
        <div style={{
          padding: "var(--space-2) var(--space-5)",
          background: "rgba(196, 77, 77, 0.08)",
          color: "var(--color-danger)",
          fontSize: "0.8125rem",
          borderTop: "1px solid var(--color-border)",
        }}>
          {error}
        </div>
      )}

      <div style={{
        padding: "var(--space-3) var(--space-5)",
        borderTop: "1px solid var(--color-border)",
        background: "var(--color-surface)",
        display: "flex",
        alignItems: "center",
        gap: "var(--space-3)",
      }}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.nativeEvent.isComposing) {
              e.preventDefault();
              void addTask();
            }
          }}
          placeholder="Add a new task..."
          style={{
            flex: 1,
            background: "var(--color-surface-2)",
            border: "1px solid var(--color-border)",
            borderRadius: "var(--radius-lg)",
            padding: "var(--space-3) var(--space-4)",
            color: "var(--color-text)",
            fontSize: "0.9375rem",
            outline: "none",
          }}
        />
        <button
          onClick={() => void addTask()}
          disabled={loading || !input.trim()}
          aria-label="Add task"
          style={{
            width: 36,
            height: 36,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            background: loading || !input.trim() ? "transparent" : "var(--color-primary)",
            border: loading || !input.trim() ? "1px solid var(--color-border)" : "none",
            borderRadius: "var(--radius-md)",
            opacity: loading || !input.trim() ? 0.4 : 1,
            transition: "opacity 150ms, background 150ms",
            cursor: loading || !input.trim() ? "not-allowed" : "pointer",
            flexShrink: 0,
          }}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
            stroke={loading || !input.trim() ? "var(--color-text-faint)" : "#fff"}
            strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
        </button>
      </div>
    </div>
  );
}

/**
 * `useSearchParams()` must sit under a Suspense boundary or the production
 * build fails; `login/page.tsx` uses the same shape for its `?next=`.
 */
export default function TasksPage() {
  return (
    <Suspense fallback={null}>
      <TasksPageInner />
    </Suspense>
  );
}
