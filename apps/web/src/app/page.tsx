"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { createClient } from "@/lib/supabase/client";
import {
  type Task,
  isTask,
  dueMeta,
  sortTasksByDueDate,
  matchesTaskFilter,
  priorityBadge,
} from "@/lib/tasks";

/* ── Type Guards ──────────────────────────────────────────
   `Task` and `isTask` now live in `@/lib/tasks`, with the priority ladder and
   the due-date vocabulary, so this screen and /tasks cannot drift apart again —
   which is exactly how priority 4 and 5 stopped appearing on /tasks. */

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

type CalEvent = {
  id: string;
  title: string;
  start_time: string;
  end_time: string;
  location?: string;
  calendar_name?: string;
};

/* ── Pure helpers ───────────────────────────────────────────
   Every one of these takes `now` as an argument rather than reading the
   clock. A date computed during render is a hydration mismatch waiting to
   happen, and this page has already been burned by a clock frozen at mount. */

function greetingFor(now: Date): string {
  const h = now.getHours();
  if (h < 5) return "Good evening";
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

function clock(date: string): string {
  return new Date(date).toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: true,
  });
}

function minutesUntil(date: string, now: Date): number {
  return Math.round((new Date(date).getTime() - now.getTime()) / 60_000);
}

/** "in 40 min" / "started 5 min ago" — the figure a glance actually needs. */
function untilLabel(date: string, now: Date): string {
  const mins = minutesUntil(date, now);
  if (mins < -60) return "";
  if (mins < 0) return `started ${Math.abs(mins)} min ago`;
  if (mins < 60) return `in ${mins} min`;
  const hours = Math.floor(mins / 60);
  const rest = mins % 60;
  if (hours < 24) return rest ? `in ${hours}h ${rest}m` : `in ${hours}h`;
  return `in ${Math.round(hours / 24)}d`;
}

function ago(from: Date, now: Date): string {
  const mins = Math.round((now.getTime() - from.getTime()) / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} hr ago`;
  const days = Math.round(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

/* ── Small presentational pieces ────────────────────────── */

function CheckIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <polyline points="20 6 9 17 4 12" />
    </svg>
  );
}

function StatusPill({
  online,
  lastSeen,
  now,
  local,
}: {
  online: boolean;
  lastSeen: Date | null;
  now: Date;
  local: boolean;
}) {
  return (
    <div className="col" style={{ alignItems: "flex-end", gap: 2, marginTop: "var(--space-1)" }}>
      <div className="row" style={{ gap: 6 }}>
        <span
          aria-hidden
          style={{
            width: 8,
            height: 8,
            borderRadius: "50%",
            background: online ? "var(--color-success)" : "var(--color-danger)",
            boxShadow: online
              ? "0 0 8px var(--color-success-faint)"
              : "0 0 8px var(--color-danger-faint)",
          }}
        />
        <span className="label" style={{ textTransform: "uppercase", letterSpacing: "0.05em", fontWeight: 600 }}>
          {online ? "Online" : "Offline"}
        </span>
      </div>
      {online && local && (
        <span className="t-2xs" style={{ color: "var(--color-warning)", fontWeight: 500 }}>
          Local / low power
        </span>
      )}
      {!online && lastSeen && <span className="t-2xs faint">seen {ago(lastSeen, now)}</span>}
    </div>
  );
}

function TaskSkeleton() {
  return (
    <div className="grouped-list">
      {[0, 1, 2].map((i) => (
        <div key={i} className="grouped-list-item">
          <span className="skeleton" style={{ width: 30, height: 30, borderRadius: "50%" }} />
          <span className="skeleton" style={{ flex: 1, height: 14, maxWidth: 220 - i * 30 }} />
        </div>
      ))}
    </div>
  );
}

/* ── Page ───────────────────────────────────────────────── */

export default function DashboardPage() {
  const supabase = useMemo(() => createClient(), []);

  // Null until the browser has a clock. The server and the browser format a
  // local date differently, so this doubles as the hydration guard `mounted`
  // used to be — one piece of state instead of two saying the same thing.
  //
  // Ticking rather than set once. It was read by `isOnline`, which compares it
  // to the worker's last heartbeat, so a value frozen at mount meant the
  // dashboard kept reporting "online" indefinitely after the worker stopped.
  //
  // The first read happens in a timeout callback, not in the effect body: a
  // setState directly in an effect body is the cascading-render pattern React
  // now rejects, and a zero-delay timeout is indistinguishable on screen.
  const [currentTime, setCurrentTime] = useState<Date | null>(null);
  useEffect(() => {
    const tick = () => setCurrentTime(new Date());
    const soon = setTimeout(tick, 0);
    const every = setInterval(tick, 30000);
    return () => {
      clearTimeout(soon);
      clearInterval(every);
    };
  }, []);
  const mounted = currentTime !== null;

  const [brief, setBrief] = useState<Message | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [approvalsCount, setApprovalsCount] = useState(0);
  const [nextEvent, setNextEvent] = useState<CalEvent | null>(null);
  const [completing, setCompleting] = useState<Set<string>>(new Set());
  const [refreshingBrief, setRefreshingBrief] = useState(false);
  const [lastHeartbeat, setLastHeartbeat] = useState<Date | null>(null);
  const [isLocalMode, setIsLocalMode] = useState(false);
  // Distinguishes "still loading" from "genuinely empty". Without it the empty
  // state flashed before the first query returned, which reads as bad news.
  const [loaded, setLoaded] = useState(false);

  const refreshBrief = async () => {
    setRefreshingBrief(true);
    const { data: { user } } = await supabase.auth.getUser();
    if (user) {
      const { data } = await supabase
        .from("messages")
        .select("*")
        .eq("user_id", user.id)
        .eq("role", "assistant")
        .eq("model_used", "system")
        .order("created_at", { ascending: false })
        .limit(1)
        .maybeSingle();
      if (data && isMessage(data)) {
        setBrief(data);
      }
    }
    setRefreshingBrief(false);
  };

  useEffect(() => {
    let cancelled = false;

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

      // 20 rather than 5: the strip shows 5, but "3 late, 2 due today" cannot
      // be counted from the five rows that happened to sort highest.
      const pTasks = supabase
        .from("tasks")
        .select("*")
        .eq("user_id", user.id)
        .eq("status", "open")
        .eq("is_archived", false)
        .order("created_at", { ascending: true })
        .limit(20);

      const pApprovals = supabase
        .from("action_queue")
        .select("*", { count: "exact", head: true })
        .eq("user_id", user.id)
        .eq("status", "awaiting_approval");

      const pNextEvent = supabase
        .from("calendar_events")
        .select("id, title, start_time, end_time, location, calendar_name")
        .eq("user_id", user.id)
        .gt("end_time", new Date().toISOString())
        .order("start_time", { ascending: true })
        .limit(1)
        .maybeSingle();

      const pHeartbeat = supabase
        .from("mac_heartbeat")
        .select("last_seen")
        .eq("id", 1)
        .maybeSingle();

      const pRecentMessage = supabase
        .from("messages")
        .select("model_used")
        .eq("role", "assistant")
        .order("created_at", { ascending: false })
        .limit(1)
        .maybeSingle();

      const [resBrief, resTasks, resApprovals, resNextEvent, resHeartbeat, resRecentMessage] =
        await Promise.all([pBrief, pTasks, pApprovals, pNextEvent, pHeartbeat, pRecentMessage]);

      if (cancelled) return;

      setBrief(resBrief.data && isMessage(resBrief.data) ? resBrief.data : null);
      if (resTasks.data) setTasks(resTasks.data.filter(isTask));
      if (resApprovals.count !== null) setApprovalsCount(resApprovals.count);
      setNextEvent(resNextEvent.data ? (resNextEvent.data as CalEvent) : null);
      if (resHeartbeat.data && resHeartbeat.data.last_seen) {
        setLastHeartbeat(new Date(resHeartbeat.data.last_seen));
      }
      if (resRecentMessage.data && resRecentMessage.data.model_used) {
        setIsLocalMode(resRecentMessage.data.model_used === "ollama");
      }
      setLoaded(true);
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
            setBrief(row);
          }
        }
      )
      .subscribe();

    const pollInterval = setInterval(() => {
      void loadData();
    }, 30000) as unknown as number;

    return () => {
      cancelled = true;
      clearInterval(pollInterval);
      supabase.removeChannel(channel);
    };
  }, [supabase]);

  const toggleTask = async (task: Task) => {
    if (completing.has(task.id)) return;

    setCompleting((prev) => new Set(prev).add(task.id));

    try {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) return;

      const { error } = await supabase
        .from("tasks")
        .update({ status: "done", completed_at: new Date().toISOString() })
        .eq("id", task.id)
        .eq("user_id", user.id);

      if (!error) {
        setTasks((prev) => prev.filter((t) => t.id !== task.id));
      }
    } finally {
      setCompleting((prev) => {
        const next = new Set(prev);
        next.delete(task.id);
        return next;
      });
    }
  };

  const now = currentTime;
  const ordered = useMemo(() => sortTasksByDueDate(tasks), [tasks]);

  // Same predicate, same `now` as the list below and as /tasks?filter=… — so a
  // chip cannot promise a count its destination view does not show.
  const overdueCount = now ? ordered.filter((t) => matchesTaskFilter(t, "late", now)).length : 0;
  const todayCount = now ? ordered.filter((t) => matchesTaskFilter(t, "today", now)).length : 0;

  const isOnline = lastHeartbeat && currentTime
    ? currentTime.getTime() - lastHeartbeat.getTime() < 120000
    : false;

  const dateStr = currentTime
    ? currentTime.toLocaleDateString("en-US", { weekday: "long", day: "numeric", month: "long" })
    : "";

  return (
    <div
      className="col"
      style={{
        padding: "var(--space-6) var(--space-5)",
        gap: "var(--space-6)",
        maxWidth: "800px",
        margin: "0 auto",
        width: "100%",
      }}
    >
      {/* Date header */}
      <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
        <div style={{ minWidth: 0 }}>
          <h1
            className="t-lg"
            style={{ fontWeight: 600, color: "var(--color-text-muted)", letterSpacing: "-0.02em" }}
          >
            {mounted ? (
              dateStr
            ) : (
              <span className="skeleton" style={{ display: "inline-block", width: 190, height: 24 }} />
            )}
          </h1>
          <p className="t-md muted" style={{ marginTop: "var(--space-1)" }}>
            {currentTime ? (
              greetingFor(currentTime)
            ) : (
              <span className="skeleton" style={{ display: "inline-block", width: 110, height: 14 }} />
            )}
          </p>
        </div>

        {mounted && currentTime && (
          <StatusPill
            online={isOnline}
            lastSeen={lastHeartbeat}
            now={currentTime}
            local={isLocalMode}
          />
        )}
      </div>

      {/* Offline is a state, not a dot. The old screen showed a red dot with no
          explanation, so "Sunday is asleep" and "something is broken" looked
          identical — and the difference decides whether you wait or fix it. */}
      {mounted && currentTime && !isOnline && (
        <div
          className="card card-tight"
          style={{ borderColor: "var(--color-warning)", display: "flex", gap: "var(--space-3)", alignItems: "flex-start" }}
        >
          <span
            aria-hidden
            style={{
              width: 8,
              height: 8,
              borderRadius: "50%",
              background: "var(--color-warning)",
              marginTop: 6,
              flexShrink: 0,
            }}
          />
          <div>
            <p className="t-sm" style={{ fontWeight: 600 }}>
              The worker is offline
            </p>
            <p className="t-xs muted" style={{ marginTop: 2 }}>
              {lastHeartbeat ? `Last heartbeat ${ago(lastHeartbeat, currentTime)}. ` : "No heartbeat recorded yet. "}
              Chat, briefs and approvals need it running. Tasks you tick here still save.
            </p>
          </div>
        </div>
      )}

      {/* Approvals */}
      {approvalsCount > 0 && (
        <Link href="/approvals" style={{ textDecoration: "none" }}>
          <div
            className="card card-tight tappable"
            style={{ display: "flex", alignItems: "center", gap: "var(--space-3)" }}
          >
            <span
              aria-hidden
              style={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                background: "var(--color-warning)",
                flexShrink: 0,
              }}
            />
            <span className="t-md" style={{ fontWeight: 500 }}>
              {approvalsCount} action{approvalsCount === 1 ? "" : "s"} waiting for your approval
            </span>
          </div>
        </Link>
      )}

      {/* What actually needs attention today. Counted from the same rows, so it
          cannot disagree with the list below it. */}
      {loaded && now && (overdueCount > 0 || todayCount > 0) && (
        <div className="row gap-2" style={{ flexWrap: "wrap" }}>
          {overdueCount > 0 && (
            <Link href="/tasks?filter=late" className="chip chip-danger" style={{ textDecoration: "none" }}>
              {overdueCount} late
            </Link>
          )}
          {todayCount > 0 && (
            <Link href="/tasks?filter=today" className="chip chip-warning" style={{ textDecoration: "none" }}>
              {todayCount} due today
            </Link>
          )}
        </div>
      )}

      {/* Next event */}
      {nextEvent && (
        <section>
          <div className="section-head">
            <h2 className="label" style={{ textTransform: "uppercase", letterSpacing: "0.05em", fontWeight: 600 }}>
              Next event
            </h2>
          </div>
          <Link href="/schedule" style={{ textDecoration: "none" }}>
            <div
              className="card card-tight tappable"
              style={{ borderLeft: "3px solid var(--color-primary)", display: "flex", flexDirection: "column", gap: 2 }}
            >
              <div className="row" style={{ justifyContent: "space-between", gap: "var(--space-3)" }}>
                <span className="t-md" style={{ fontWeight: 600, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {nextEvent.title}
                </span>
                <span className="t-xs faint nums" style={{ flexShrink: 0 }}>
                  {currentTime
                    ? `${clock(nextEvent.start_time)} – ${clock(nextEvent.end_time)}`
                    : "--:--"}
                </span>
              </div>
              <div className="row gap-2">
                {nextEvent.location && (
                  <span className="t-2xs faint" style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {nextEvent.location}
                  </span>
                )}
                {currentTime && untilLabel(nextEvent.start_time, currentTime) ? (
                  <span className="chip chip-primary">{untilLabel(nextEvent.start_time, currentTime)}</span>
                ) : null}
              </div>
            </div>
          </Link>
        </section>
      )}

      {/* Daily brief */}
      <section>
        <div className="section-head">
          <h2 className="label" style={{ textTransform: "uppercase", letterSpacing: "0.05em", fontWeight: 600 }}>
            Daily brief
          </h2>
          <div className="row gap-3">
            {brief && currentTime && (
              <span className="t-2xs faint nums">{clock(brief.created_at)}</span>
            )}
            <button
              type="button"
              className="link-btn"
              onClick={refreshBrief}
              disabled={refreshingBrief}
              style={{ opacity: refreshingBrief ? 0.5 : 1 }}
            >
              {refreshingBrief ? "Refreshing…" : "Refresh"}
            </button>
          </div>
        </div>
        <div className="card" aria-live="polite">
          {!loaded && !brief ? (
            <div className="col gap-2">
              <span className="skeleton" style={{ height: 13, width: "94%" }} />
              <span className="skeleton" style={{ height: 13, width: "88%" }} />
              <span className="skeleton" style={{ height: 13, width: "55%" }} />
            </div>
          ) : brief ? (
            <div className="markdown-body">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{brief.content}</ReactMarkdown>
            </div>
          ) : (
            <p className="t-md faint">No brief yet — the worker sends one at 8am.</p>
          )}
        </div>
      </section>

      {/* Open tasks */}
      <section>
        <div className="section-head">
          <h2 className="label" style={{ textTransform: "uppercase", letterSpacing: "0.05em", fontWeight: 600 }}>
            Open tasks
          </h2>
          {loaded && ordered.length > 0 && (
            <span className="t-2xs faint nums">{ordered.length}</span>
          )}
        </div>

        {!loaded ? (
          <TaskSkeleton />
        ) : ordered.length > 0 ? (
          <div className="grouped-list">
            {ordered.slice(0, 5).map((task) => {
              const busy = completing.has(task.id);
              const meta = now ? dueMeta(task.due_date, now) : null;
              const toneClass = meta ? (meta.tone === "muted" ? "chip" : `chip chip-${meta.tone}`) : "";
              const badge = priorityBadge(task.priority);

              return (
                <div key={task.id} className="grouped-list-item tappable" style={{ opacity: busy ? 0.55 : 1 }}>
                  <button
                    type="button"
                    className="tap"
                    onClick={() => void toggleTask(task)}
                    disabled={busy}
                    aria-label={`Mark “${task.title}” done`}
                    aria-pressed={busy}
                    style={{ color: "var(--color-success)" }}
                  >
                    <span
                      aria-hidden
                      style={{
                        width: 22,
                        height: 22,
                        borderRadius: "50%",
                        border: `2px solid ${busy ? "var(--color-success)" : "var(--color-border-strong)"}`,
                        background: busy ? "var(--color-success-faint)" : "transparent",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        transition: "background 150ms ease, border-color 150ms ease",
                      }}
                    >
                      {busy && <CheckIcon />}
                    </span>
                  </button>

                  <div style={{ flex: 1, minWidth: 0 }}>
                    {/* Two lines, then clamp. On one clipped line the badge
                        took 53px of a 217px column and a perfectly ordinary
                        title — "Review the travel plan for Thursday" — became
                        "…for Th…", with no way to read the rest on a phone. */}
                    <div
                      className="t-md"
                      style={{
                        display: "-webkit-box",
                        WebkitBoxOrient: "vertical",
                        WebkitLineClamp: 2,
                        overflow: "hidden",
                        overflowWrap: "anywhere",
                      }}
                    >
                      {task.title}
                    </div>
                    {(meta || task.category) && (
                      <div className="row gap-2" style={{ marginTop: 2 }}>
                        {meta && <span className={toneClass}>{meta.label}</span>}
                        {task.category && <span className="t-2xs faint">{task.category}</span>}
                      </div>
                    )}
                  </div>

                  {badge && <span className={badge.className}>{badge.label}</span>}
                </div>
              );
            })}
          </div>
        ) : (
          <div className="card" style={{ textAlign: "center" }}>
            <p className="t-md faint">All caught up for now.</p>
            <p className="t-2xs faint" style={{ marginTop: 2 }}>
              Anything you mention in chat can become a task.
            </p>
          </div>
        )}

        <Link
          href="/tasks"
          className="link-btn"
          style={{ display: "inline-block", marginTop: "var(--space-3)" }}
        >
          View all tasks →
        </Link>
      </section>
    </div>
  );
}
