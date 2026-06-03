"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";

const ONLINE_THRESHOLD_MS = 2 * 60 * 1000;
const POLL_INTERVAL_MS = 30 * 1000;

/* ── Time-aware greeting ─────────────────────────────────── */
function getGreeting(): string {
  const h = new Date().getHours();
  if (h < 5)  return "Good evening";
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

/* ── Status dot ──────────────────────────────────────────── */
function StatusDot({ online }: { online: boolean }) {
  return (
    <span style={{
      display: "inline-block",
      width: 6, height: 6,
      borderRadius: "50%",
      background: online ? "var(--color-success)" : "var(--color-text-faint)",
      boxShadow: online ? "0 0 6px var(--color-success)" : "none",
      flexShrink: 0,
    }} />
  );
}

/* ── Dashboard card ──────────────────────────────────────── */
function Card({ title, action, children }: {
  title: string;
  action?: { label: string; href: string };
  children: React.ReactNode;
}) {
  return (
    <div style={{
      background: "var(--color-surface)",
      border: "1px solid var(--color-border)",
      borderRadius: "var(--radius-lg)",
      padding: "var(--space-5)",
    }}>
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        marginBottom: "var(--space-3)",
      }}>
        <h3 style={{
          fontSize: "0.6875rem",
          fontWeight: 600,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: "var(--color-text-faint)",
        }}>{title}</h3>
        {action && (
          <Link href={action.href} style={{
            fontSize: "0.6875rem",
            color: "var(--color-primary)",
            textDecoration: "none",
          }}>{action.label}</Link>
        )}
      </div>
      {children}
    </div>
  );
}

/* ── Task type ───────────────────────────────────────────── */
type Task = {
  id: string;
  title: string;
  category: string | null;
  priority: number;
  due_date: string | null;
  status: string;
};

type Briefing = {
  id: string;
  content: string;
  briefing_date: string;
};

export default function DashboardPage() {
  const supabase = useMemo(() => createClient(), []);
  const [online, setOnline] = useState(false);
  const [loading, setLoading] = useState(true);
  const [pendingCount, setPendingCount] = useState(0);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [briefing, setBriefing] = useState<Briefing | null>(null);

  /* Worker heartbeat */
  useEffect(() => {
    let cancelled = false;

    const fetchHeartbeat = async () => {
      const { data, error } = await supabase
        .from("mac_heartbeat")
        .select("last_seen")
        .eq("id", 1)
        .maybeSingle();

      if (cancelled) return;

      if (error || !data) {
        setOnline(false);
        setLoading(false);
        return;
      }

      const row = data as { last_seen: string | null };
      if (!row.last_seen) {
        setOnline(false);
      } else {
        const age = Date.now() - new Date(row.last_seen).getTime();
        setOnline(age >= 0 && age <= ONLINE_THRESHOLD_MS);
      }
      setLoading(false);
    };

    void fetchHeartbeat();
    const interval = setInterval(() => { void fetchHeartbeat(); }, POLL_INTERVAL_MS);
    return () => { cancelled = true; clearInterval(interval); };
  }, [supabase]);

  /* Pending approval count */
  useEffect(() => {
    let cancelled = false;

    const fetchPending = async () => {
      const { count, error } = await supabase
        .from("action_queue")
        .select("*", { count: "exact", head: true })
        .eq("status", "pending")
        .is("approved", null)
        .neq("tier", "auto");
      if (!cancelled && !error && count !== null) setPendingCount(count);
    };

    void fetchPending();
    const ch = supabase
      .channel("dash-approvals")
      .on("postgres_changes", { event: "*", schema: "public", table: "action_queue" }, () => { void fetchPending(); })
      .subscribe();

    return () => { cancelled = true; supabase.removeChannel(ch); };
  }, [supabase]);

  /* Due tasks (today + overdue) */
  useEffect(() => {
    let cancelled = false;
    const today = new Date().toISOString().split("T")[0];

    const fetchTasks = async () => {
      const { data } = await supabase
        .from("tasks")
        .select("id,title,category,priority,due_date,status")
        .in("status", ["open", "in_progress"])
        .lte("due_date", today)
        .order("priority", { ascending: true })
        .limit(5);
      if (!cancelled && data) setTasks(data as Task[]);
    };

    void fetchTasks();
    return () => { cancelled = true; };
  }, [supabase]);

  /* Today's briefing */
  useEffect(() => {
    let cancelled = false;
    const today = new Date().toISOString().split("T")[0];

    const fetchBriefing = async () => {
      const { data } = await supabase
        .from("daily_briefings")
        .select("id,content,briefing_date")
        .eq("briefing_date", today)
        .maybeSingle();
      if (!cancelled && data) setBriefing(data as Briefing);
    };

    void fetchBriefing();
    return () => { cancelled = true; };
  }, [supabase]);

  const now = new Date();
  const dateStr = now.toLocaleDateString("en-AU", {
    weekday: "long",
    day: "numeric",
    month: "long",
  });

  return (
    <div style={{ maxWidth: "800px", margin: "0 auto", padding: "var(--space-8) var(--space-5)" }}>
      {/* Greeting */}
      <div style={{ marginBottom: "var(--space-6)" }}>
        <h1 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "var(--space-1)" }}>
          {getGreeting()}, Alstone.
        </h1>
        <p style={{ fontSize: "0.8125rem", color: "var(--color-text-muted)" }}>
          {dateStr}
        </p>
      </div>

      {/* Cards */}
      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>

        {/* Worker status */}
        <Card title="System">
          <div style={{ display: "flex", alignItems: "center", gap: "var(--space-3)" }}>
            <StatusDot online={online} />
            <span style={{ fontSize: "0.875rem", color: "var(--color-text)" }}>
              {loading ? "Checking worker…" : online ? "Mac worker online" : "Mac worker offline"}
            </span>
          </div>
          {pendingCount > 0 && (
            <Link href="/approvals" style={{ textDecoration: "none" }}>
              <div style={{
                marginTop: "var(--space-3)",
                display: "flex", alignItems: "center", gap: "var(--space-2)",
              }}>
                <span style={{
                  width: 18, height: 18, borderRadius: "9999px",
                  background: "var(--color-danger)", color: "#fff",
                  fontSize: "0.625rem", fontWeight: 700,
                  display: "flex", alignItems: "center", justifyContent: "center",
                }}>{pendingCount}</span>
                <span style={{ fontSize: "0.8125rem", color: "var(--color-text-muted)" }}>
                  action{pendingCount === 1 ? "" : "s"} awaiting approval
                </span>
              </div>
            </Link>
          )}
        </Card>

        {/* Morning briefing */}
        {briefing && (
          <Card title="Daily Briefing">
            <div
              className="markdown-body"
              style={{ fontSize: "0.8125rem", color: "var(--color-text)" }}
              dangerouslySetInnerHTML={{ __html: briefing.content.replace(/\n/g, "<br/>") }}
            />
          </Card>
        )}

        {/* Due tasks */}
        <Card title="Due Tasks" action={{ label: "View all →", href: "/tasks" }}>
          {tasks.length === 0 ? (
            <p style={{ fontSize: "0.8125rem", color: "var(--color-text-faint)" }}>
              No tasks due today.
            </p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
              {tasks.map((t) => (
                <div key={t.id} style={{
                  display: "flex", alignItems: "center", gap: "var(--space-3)",
                  fontSize: "0.8125rem",
                }}>
                  <span style={{
                    width: 4, height: 4, borderRadius: "50%", flexShrink: 0,
                    background: t.priority <= 2 ? "var(--color-danger)" : "var(--color-text-faint)",
                  }} />
                  <span style={{ color: "var(--color-text)", flex: 1 }}>{t.title}</span>
                  {t.category && (
                    <span style={{ fontSize: "0.6875rem", color: "var(--color-text-faint)" }}>
                      {t.category}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </Card>

        {/* Schedule placeholder */}
        <Card title="Today's Schedule">
          <p style={{ fontSize: "0.8125rem", color: "var(--color-text-faint)" }}>
            Calendar events will appear here once the morning briefing runs.
          </p>
        </Card>

        {/* News placeholder */}
        <Card title="News">
          <p style={{ fontSize: "0.8125rem", color: "var(--color-text-faint)" }}>
            News digest will appear here after feeds are configured.
          </p>
        </Card>
      </div>
    </div>
  );
}
