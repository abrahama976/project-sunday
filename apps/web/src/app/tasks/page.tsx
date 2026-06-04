"use client";

import { useEffect, useMemo, useState } from "react";
import { createClient } from "@/lib/supabase/client";

type Task = {
  id: string;
  title: string;
  status: "open" | "done";
  priority: 1 | 2 | 3;
  due_date: string | null;
  category: string | null;
  is_archived: boolean;
  created_at: string;
};

function isTask(x: unknown): x is Task {
  if (!x || typeof x !== "object") return false;
  const o = x as Record<string, unknown>;
  return (
    typeof o.id === "string" &&
    typeof o.title === "string" &&
    (o.status === "open" || o.status === "done") &&
    (o.priority === 1 || o.priority === 2 || o.priority === 3) &&
    (o.due_date === null || typeof o.due_date === "string") &&
    (o.category === null || typeof o.category === "string") &&
    typeof o.is_archived === "boolean" &&
    typeof o.created_at === "string"
  );
}

const PRIORITY_LABELS: Record<1 | 2 | 3, string> = { 1: "Low", 2: "Normal", 3: "High" };
const PRIORITY_COLORS: Record<1 | 2 | 3, string> = {
  1: "var(--color-text-faint)",
  2: "var(--color-primary)",
  3: "var(--color-danger)",
};

export default function TasksPage() {
  const supabase = useMemo(() => createClient(), []);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
            void loadTasks();
          } else if (status === "CHANNEL_ERROR" || status === "TIMED_OUT") {
            setError(`Realtime unavailable: ${err?.message ?? status}. Refresh to see updates.`);
            void loadTasks();
          }
        });

      pollInterval = setInterval(() => {
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
        {tasks.length === 0 && !error && (
          <div style={{
            margin: "auto",
            textAlign: "center",
            color: "var(--color-text-faint)",
            paddingTop: "4rem",
          }}>
            <p style={{ fontSize: "1rem", color: "var(--color-text-muted)", fontWeight: 500 }}>
              No open tasks.
            </p>
            <p style={{ fontSize: "0.8125rem", marginTop: "var(--space-2)" }}>
              Enjoy the clear day!
            </p>
          </div>
        )}

        {tasks.map((task) => (
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
              onClick={() => void toggleTask(task)}
              style={{
                width: 20,
                height: 20,
                borderRadius: "50%",
                border: `2px solid ${task.status === "done" ? "var(--color-primary)" : "var(--color-border)"}`,
                background: task.status === "done" ? "var(--color-primary)" : "transparent",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                cursor: "pointer",
                flexShrink: 0,
                marginTop: 2,
              }}
            >
              {task.status === "done" && (
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
              )}
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
              }}>
                <span style={{ color: PRIORITY_COLORS[task.priority] }}>
                  {PRIORITY_LABELS[task.priority]} Priority
                </span>
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
          </div>
        ))}
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
