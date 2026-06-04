"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
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

/* ── Progress Bar Component ──────────────────────────────── */
function ProgressBar({ label, current, max, unit, colorVar }: { label: string, current: number, max: number, unit: string, colorVar: string }) {
  const percentage = Math.min(100, Math.max(0, (current / max) * 100));
  
  return (
    <div style={{ marginBottom: "var(--space-4)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "var(--space-2)", fontSize: "0.8125rem" }}>
        <span style={{ fontWeight: 500, color: "var(--color-text)" }}>{label}</span>
        <span style={{ color: "var(--color-text-muted)" }}>{current} / {max} {unit}</span>
      </div>
      <div style={{
        height: "6px",
        background: "var(--color-surface-2)",
        borderRadius: "9999px",
        overflow: "hidden"
      }}>
        <div style={{
          height: "100%",
          width: `${percentage}%`,
          background: colorVar,
          borderRadius: "9999px",
          transition: "width 1s cubic-bezier(0.4, 0, 0.2, 1)",
        }} />
      </div>
    </div>
  );
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
      transition: "background 0.3s ease, box-shadow 0.3s ease",
    }} />
  );
}

/* ── Dashboard card ──────────────────────────────────────── */
function Card({ title, action, children, href }: {
  title: string;
  action?: { label: string; href: string };
  children: React.ReactNode;
  href?: string;
}) {
  const content = (
    <div style={{
      background: "var(--color-surface)",
      border: "1px solid var(--color-border)",
      borderRadius: "var(--radius-xl)",
      padding: "var(--space-5)",
      boxShadow: "var(--shadow-sm)",
      transition: "transform 150ms ease, background 150ms ease",
      cursor: href ? "pointer" : "default",
    }} className={href ? "hover:scale-[1.02] hover:bg-white/5" : ""}>
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        marginBottom: "var(--space-4)",
      }}>
        <h3 style={{
          fontSize: "0.75rem",
          fontWeight: 600,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: "var(--color-text-faint)",
        }}>{title}</h3>
        {action && (
          <Link href={action.href} style={{
            fontSize: "0.75rem",
            fontWeight: 500,
            color: "var(--color-primary)",
            textDecoration: "none",
          }}>{action.label}</Link>
        )}
      </div>
      {children}
    </div>
  );

  if (href) {
    return <Link href={href} style={{ textDecoration: "none", color: "inherit" }}>{content}</Link>;
  }
  return content;
}

/* ── Types ───────────────────────────────────────────── */
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

type HealthLog = {
  metric: string;
  value: number;
};

export default function DashboardPage() {
  const supabase = useMemo(() => createClient(), []);
  const [online, setOnline] = useState(false);
  const [loading, setLoading] = useState(true);
  const [pendingCount, setPendingCount] = useState(0);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [healthLogs, setHealthLogs] = useState<HealthLog[]>([]);
  const [briefing, setBriefing] = useState<Briefing | null>(null);
  const [userName, setUserName] = useState("");

  /* Fetch display name */
  useEffect(() => {
    (async () => {
      const { data: profile } = await supabase.from("user_profile").select("content").limit(1).maybeSingle();
      if (profile?.content) {
        const match = profile.content.match(/^#\s+(.+)/m);
        if (match) { setUserName(match[1].trim()); return; }
      }
      const { data: { user } } = await supabase.auth.getUser();
      if (user?.email) setUserName(user.email.split("@")[0]);
    })();
  }, [supabase]);

  /* Worker heartbeat */
  useEffect(() => {
    let cancelled = false;
    const fetchHeartbeat = async () => {
      const { data, error } = await supabase.from("mac_heartbeat").select("last_seen").eq("id", 1).maybeSingle();
      if (cancelled) return;
      if (error || !data || !data.last_seen) {
        setOnline(false);
      } else {
        const age = Date.now() - new Date(data.last_seen).getTime();
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
      const { count, error } = await supabase.from("action_queue").select("*", { count: "exact", head: true }).eq("status", "pending").is("approved", null).neq("tier", "auto");
      if (!cancelled && !error && count !== null) setPendingCount(count);
    };
    void fetchPending();
    const ch = supabase.channel("dash-approvals")
      .on("postgres_changes", { event: "*", schema: "public", table: "action_queue" }, () => { void fetchPending(); })
      .subscribe();
    return () => { cancelled = true; supabase.removeChannel(ch); };
  }, [supabase]);

  /* Tasks (completion stats and due tasks) */
  useEffect(() => {
    let cancelled = false;
    
    const tzOffset = (new Date()).getTimezoneOffset() * 60000;
    const localISOTime = (new Date(Date.now() - tzOffset)).toISOString().slice(0, -1);
    const today = localISOTime.split("T")[0];

    const fetchTasks = async () => {
      const { data } = await supabase
        .from("tasks")
        .select("id,title,category,priority,due_date,status")
        .lte("due_date", today)
        .order("priority", { ascending: true });
      if (!cancelled && data) setTasks(data as Task[]);
    };

    void fetchTasks();
    const ch = supabase.channel("dash-tasks")
      .on("postgres_changes", { event: "*", schema: "public", table: "tasks" }, () => { void fetchTasks(); })
      .subscribe();
    return () => { cancelled = true; supabase.removeChannel(ch); };
  }, [supabase]);

  /* Health logs */
  useEffect(() => {
    let cancelled = false;
    
    const tzOffset = (new Date()).getTimezoneOffset() * 60000;
    const localISOTime = (new Date(Date.now() - tzOffset)).toISOString().slice(0, -1);
    const today = localISOTime.split("T")[0];

    const fetchHealth = async () => {
      const { data } = await supabase.from("health_logs").select("metric,value").eq("log_date", today);
      if (!cancelled && data) setHealthLogs(data as HealthLog[]);
    };

    void fetchHealth();
    const ch = supabase.channel("dash-health")
      .on("postgres_changes", { event: "*", schema: "public", table: "health_logs" }, () => { void fetchHealth(); })
      .subscribe();
    return () => { cancelled = true; supabase.removeChannel(ch); };
  }, [supabase]);

  /* Today's briefing */
  useEffect(() => {
    let cancelled = false;
    const tzOffset = (new Date()).getTimezoneOffset() * 60000;
    const localISOTime = (new Date(Date.now() - tzOffset)).toISOString().slice(0, -1);
    const today = localISOTime.split("T")[0];

    const fetchBriefing = async () => {
      const { data } = await supabase.from("daily_briefings").select("id,content,briefing_date").eq("briefing_date", today).maybeSingle();
      if (!cancelled && data) setBriefing(data as Briefing);
    };

    void fetchBriefing();
    return () => { cancelled = true; };
  }, [supabase]);

  const now = new Date();
  const dateStr = now.toLocaleDateString("en-AU", { weekday: "long", day: "numeric", month: "long" });

  /* Calculate Stats */
  const validTasks = tasks.filter(t => t.status !== "cancelled");
  const completedTasks = validTasks.filter(t => t.status === "done").length;
  const totalTasks = validTasks.length;
  const dueTasks = validTasks.filter(t => t.status === "open" || t.status === "in_progress").slice(0, 4);

  const totalWater = healthLogs.filter(l => l.metric === "water").reduce((acc, l) => acc + Number(l.value || 0), 0);
  const totalSleep = healthLogs.filter(l => l.metric === "sleep_hours").reduce((acc, l) => acc + Number(l.value || 0), 0);

  return (
    <div style={{ maxWidth: "800px", margin: "0 auto", padding: "var(--space-8) var(--space-5)", paddingBottom: "100px" }}>
      {/* Greeting */}
      <div style={{ marginBottom: "var(--space-8)" }}>
        <h1 style={{ fontSize: "1.75rem", fontWeight: 600, marginBottom: "var(--space-1)", letterSpacing: "-0.02em", color: "var(--color-text)" }}>
          {getGreeting()}{userName ? `, ${userName}.` : "."}
        </h1>
        <p style={{ fontSize: "0.9375rem", color: "var(--color-text-muted)" }}>
          {dateStr}
        </p>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>

        {/* Worker status & Approvals */}
        <div style={{ display: "grid", gridTemplateColumns: pendingCount > 0 ? "1fr 1fr" : "1fr", gap: "var(--space-3)" }}>
          <Card title="System">
            <div style={{ display: "flex", alignItems: "center", gap: "var(--space-3)" }}>
              <StatusDot online={online} />
              <span style={{ fontSize: "0.875rem", color: "var(--color-text)", fontWeight: 500 }}>
                {loading ? "Checking worker…" : online ? "Mac worker online" : "Mac worker offline"}
              </span>
            </div>
          </Card>

          {pendingCount > 0 && (
            <Card title="Action Required" href="/approvals">
              <div style={{ display: "flex", alignItems: "center", gap: "var(--space-3)" }}>
                <span style={{
                  width: 24, height: 24, borderRadius: "9999px",
                  background: "var(--color-danger)", color: "#fff",
                  fontSize: "0.75rem", fontWeight: 700,
                  display: "flex", alignItems: "center", justifyContent: "center",
                }}>{pendingCount}</span>
                <span style={{ fontSize: "0.875rem", color: "var(--color-text)", fontWeight: 500 }}>
                  Awaiting approval
                </span>
              </div>
            </Card>
          )}
        </div>

        {/* Visual Progress Dashboard */}
        <Card title="Today's Progress">
          <ProgressBar 
            label="Tasks Completed" 
            current={completedTasks} 
            max={totalTasks === 0 ? 1 : totalTasks} 
            unit="tasks" 
            colorVar="var(--color-brand)" 
          />
          <ProgressBar 
            label="Hydration" 
            current={totalWater} 
            max={3000} 
            unit="ml" 
            colorVar="#4f88a3" 
          />
          <ProgressBar 
            label="Sleep" 
            current={totalSleep} 
            max={8} 
            unit="hrs" 
            colorVar="#8a7ba7" 
          />
        </Card>

        {/* Due tasks */}
        <Card title="Priority Tasks" action={{ label: "View all →", href: "/tasks" }}>
          {dueTasks.length === 0 ? (
            <p style={{ fontSize: "0.875rem", color: "var(--color-text-faint)", textAlign: "center", padding: "var(--space-4) 0" }}>
              No tasks due right now. You're all caught up!
            </p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
              {dueTasks.map((t) => (
                <div key={t.id} style={{
                  display: "flex", alignItems: "center", gap: "var(--space-3)",
                  fontSize: "0.875rem",
                  padding: "var(--space-2) 0",
                  borderBottom: "1px solid var(--color-surface-offset)"
                }}>
                  <div style={{
                    width: 16, height: 16, borderRadius: "50%", flexShrink: 0,
                    border: `2px solid ${t.priority <= 2 ? 'var(--color-danger)' : 'var(--color-text-faint)'}`,
                  }} />
                  <span style={{ color: "var(--color-text)", flex: 1, fontWeight: 500 }}>{t.title}</span>
                  {t.category && (
                    <span style={{ fontSize: "0.6875rem", color: "var(--color-text-muted)", background: "var(--color-surface-2)", padding: "2px 6px", borderRadius: "4px" }}>
                      {t.category}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </Card>

        {/* Morning briefing */}
        {briefing && (
          <Card title="Daily Briefing">
            <div
              className="markdown-body"
              style={{ fontSize: "0.875rem", color: "var(--color-text)", lineHeight: 1.6 }}
            >
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {briefing.content}
              </ReactMarkdown>
            </div>
          </Card>
        )}

      </div>
    </div>
  );
}
