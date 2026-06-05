"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { createClient } from "@/lib/supabase/client";

/* ── Type Guards ────────────────────────────────────────── */
type Task = {
  id: string;
  title: string;
  status: "open" | "done";
  priority: 0 | 1 | 2 | 3;
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
    (o.priority === 0 || o.priority === 1 || o.priority === 2 || o.priority === 3) &&
    (o.due_date === null || typeof o.due_date === "string") &&
    (o.category === null || typeof o.category === "string") &&
    typeof o.is_archived === "boolean" &&
    typeof o.created_at === "string"
  );
}

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  model_used: string | null;
  created_at: string;
};

function isMessage(x: unknown): x is Message {
  if (!x || typeof x !== "object") return false;
  const o = x as Record<string, unknown>;
  return (
    typeof o.id === "string" &&
    (o.role === "user" || o.role === "assistant") &&
    typeof o.content === "string" &&
    (o.model_used === null || typeof o.model_used === "string") &&
    typeof o.created_at === "string"
  );
}

/* ── Greeting ───────────────────────────────────────────── */
function getGreeting(): string {
  const h = new Date().getHours();
  if (h < 5)  return "Good evening";
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

/* ── Components ─────────────────────────────────────────── */
function Card({ children, href }: { children: React.ReactNode; href?: string }) {
  const content = (
    <div style={{
      background: "var(--color-surface)",
      border: "1px solid var(--color-border)",
      borderRadius: "var(--radius-lg)",
      padding: "var(--space-4) var(--space-5)",
      cursor: href ? "pointer" : "default",
    }}>
      {children}
    </div>
  );
  if (href) {
    return <Link href={href} style={{ textDecoration: "none", color: "inherit", display: "block" }}>{content}</Link>;
  }
  return content;
}

export default function DashboardPage() {
  const supabase = useMemo(() => createClient(), []);
  
  const [brief, setBrief] = useState<Message | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [approvalsCount, setApprovalsCount] = useState(0);
  const [loadingTasks, setLoadingTasks] = useState<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;
    let pollInterval: number | undefined;

    const loadData = async () => {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user || cancelled) return;

      const pBrief = supabase
        .from("messages")
        .select("*")
        .eq("user_id", user.id)
        .eq("role", "assistant")
        .eq("model_used", "system")
        .order("created_at", { ascending: false })
        .limit(1)
        .maybeSingle();

      const pTasks = supabase
        .from("tasks")
        .select("*")
        .eq("user_id", user.id)
        .eq("status", "open")
        .eq("is_archived", false)
        .order("priority", { ascending: false })
        .order("created_at", { ascending: true })
        .limit(5);

      const pApprovals = supabase
        .from("action_queue")
        .select("*", { count: "exact", head: true })
        .eq("user_id", user.id)
        .eq("status", "awaiting_approval");

      const [resBrief, resTasks, resApprovals] = await Promise.all([pBrief, pTasks, pApprovals]);

      if (cancelled) return;

      if (resBrief.data && isMessage(resBrief.data)) {
        setBrief(resBrief.data);
      } else {
        setBrief(null);
      }

      if (resTasks.data) {
        setTasks(resTasks.data.filter(isTask));
      }

      if (resApprovals.count !== null) {
        setApprovalsCount(resApprovals.count);
      }
    };

    void loadData();

    // Set up Realtime for brief updates
    const channel = supabase.channel("today-messages")
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "messages" },
        (payload) => {
          if (cancelled) return;
          const row = payload.new;
          if (isMessage(row) && row.role === "assistant" && row.model_used === "system") {
            // New brief arrived, set it
            setBrief(row);
          }
        }
      )
      .subscribe();

    pollInterval = setInterval(() => {
      void loadData();
    }, 30000) as unknown as number;

    return () => {
      cancelled = true;
      clearInterval(pollInterval);
      supabase.removeChannel(channel);
    };
  }, [supabase]);

  const toggleTask = async (task: Task) => {
    if (loadingTasks.has(task.id)) return;
    
    setLoadingTasks(prev => {
      const next = new Set(prev);
      next.add(task.id);
      return next;
    });

    try {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) return;

      const { error } = await supabase
        .from("tasks")
        .update({ status: "done", completed_at: new Date().toISOString() })
        .eq("id", task.id)
        .eq("user_id", user.id);

      if (!error) {
        setTasks(prev => prev.filter(t => t.id !== task.id));
      }
    } finally {
      setLoadingTasks(prev => {
        const next = new Set(prev);
        next.delete(task.id);
        return next;
      });
    }
  };

  const now = new Date();
  const dateStr = now.toLocaleDateString("en-US", { weekday: "long", day: "numeric", month: "long" });

  return (
    <div style={{
      display: "flex",
      flexDirection: "column",
      minHeight: "calc(100dvh - var(--nav-top-h))",
      paddingBottom: "calc(var(--nav-bottom-h) + var(--safe-area-bottom))",
    }}>
      <div style={{
        padding: "var(--space-6) var(--space-5)",
        display: "flex",
        flexDirection: "column",
        gap: "var(--space-6)",
        maxWidth: "800px",
        margin: "0 auto",
        width: "100%",
      }}>
        
        {/* Date header */}
        <div>
          <h1 style={{ fontSize: "1.75rem", fontWeight: 600, color: "var(--color-text-muted)", letterSpacing: "-0.02em" }}>
            {dateStr}
          </h1>
          <p style={{ fontSize: "0.9375rem", color: "var(--color-text-muted)", marginTop: "var(--space-1)" }}>
            {getGreeting()}
          </p>
        </div>

        {/* Approvals Badge Row */}
        {approvalsCount > 0 && (
          <Link href="/approvals" style={{ textDecoration: "none" }}>
            <div style={{
              background: "var(--color-surface)",
              border: "1px solid var(--color-border)",
              borderRadius: "var(--radius-lg)",
              padding: "var(--space-3) var(--space-4)",
              display: "flex",
              alignItems: "center",
              gap: "var(--space-3)",
            }}>
              <span style={{
                width: 8, height: 8, borderRadius: "50%",
                background: "var(--color-warning)",
                flexShrink: 0,
                display: "inline-block",
              }} />
              <span style={{ fontSize: "0.9375rem", fontWeight: 500, color: "var(--color-text)" }}>
                {approvalsCount} action{approvalsCount === 1 ? "" : "s"} waiting for your approval
              </span>
            </div>
          </Link>
        )}

        {/* Daily brief card */}
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
          <h2 style={{ fontSize: "0.75rem", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--color-text-faint)", marginLeft: "2px" }}>
            Daily Brief
          </h2>
          <Card>
            {brief ? (
              <div className="markdown-body">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {brief.content}
                </ReactMarkdown>
              </div>
            ) : (
              <div style={{ color: "var(--color-text-faint)", fontSize: "0.9375rem" }}>
                No brief yet — worker will send one at 8am.
              </div>
            )}
          </Card>
        </div>

        {/* Open tasks strip */}
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginLeft: "2px", marginRight: "2px" }}>
            <h2 style={{ fontSize: "0.75rem", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--color-text-faint)" }}>
              Open Tasks
            </h2>
          </div>
          
          <div className="grouped-list">
            {tasks.length > 0 ? (
              tasks.map((task) => {
                const isLoading = loadingTasks.has(task.id);
                
                return (
                  <div key={task.id} className="grouped-list-item" style={{
                    opacity: isLoading ? 0.5 : 1,
                  }}>
                    <button
                      onClick={() => void toggleTask(task)}
                      disabled={isLoading}
                      style={{
                        width: 20,
                        height: 20,
                        borderRadius: "50%",
                        border: "2px solid var(--color-border)",
                        background: "transparent",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        flexShrink: 0,
                      }}
                    />
                    <div style={{
                      flex: 1,
                      minWidth: 0,
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      fontSize: "0.9375rem",
                      color: "var(--color-text)",
                    }}>
                      {task.title}
                    </div>
                  </div>
                );
              })
            ) : (
              <div style={{
                padding: "var(--space-4)",
                background: "var(--color-surface)",
                border: "1px solid var(--color-border)",
                borderRadius: "var(--radius-lg)",
                color: "var(--color-text-faint)",
                fontSize: "0.9375rem",
                textAlign: "center",
              }}>
                All caught up for now.
              </div>
            )}
            
            <Link href="/tasks" style={{ 
              display: "block", 
              marginTop: "var(--space-2)", 
              marginLeft: "0",
              fontSize: "0.875rem", 
              color: "var(--color-primary)", 
              textDecoration: "none",
              fontWeight: 500,
            }}>
              View all →
            </Link>
          </div>
        </div>

      </div>
    </div>
  );
}
