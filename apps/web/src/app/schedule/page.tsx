"use client";

import { useEffect, useMemo, useState } from "react";
import { createClient } from "@/lib/supabase/client";

type Task = {
  id: string;
  title: string;
  due_date: string | null;
  status: string;
  priority: number;
};

type CalEvent = {
  id: string;
  user_id: string;
  event_id: string;
  title: string;
  start_time: string;
  end_time: string;
  calendar_name?: string;
  location?: string;
  updated_at: string;
};

/* ── Helpers ───────────────────────────────────────────────── */
function formatTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false });
}

function isAllDay(iso: string): boolean {
  // Worker stores all-day events as midnight UTC
  const d = new Date(iso);
  return d.getUTCHours() === 0 && d.getUTCMinutes() === 0 && d.getUTCSeconds() === 0;
}

function getMonday(d: Date): Date {
  const date = new Date(d);
  date.setHours(0, 0, 0, 0);
  const day = date.getDay();
  const diff = date.getDate() - day + (day === 0 ? -6 : 1);
  return new Date(date.setDate(diff));
}

function getWeekDates(current: Date): Date[] {
  const days: Date[] = [];
  const monday = getMonday(current);
  for (let i = 0; i < 7; i++) {
    const nextDay = new Date(monday);
    nextDay.setDate(monday.getDate() + i);
    days.push(nextDay);
  }
  return days;
}

/* ── Day Selector ──────────────────────────────────────────── */
function DaySelector({ selected, onChange, weekCounts }: {
  selected: Date;
  onChange: (d: Date) => void;
  weekCounts: Record<string, number>;
}) {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const days = getWeekDates(today); // current week (Mon-Sun)

  return (
    <div style={{
      display: "flex", gap: "var(--space-2)",
      marginBottom: "var(--space-6)",
      overflowX: "auto",
      paddingBottom: "var(--space-2)",
      msOverflowStyle: "none",
      scrollbarWidth: "none",
    }}>
      {days.map((d) => {
        const isSelected = d.toDateString() === selected.toDateString();
        const isToday = d.toDateString() === today.toDateString();
        return (
          <button
            key={d.toISOString()}
            onClick={() => onChange(d)}
            style={{
              display: "flex", flexDirection: "column", alignItems: "center",
              padding: "var(--space-2) var(--space-3)",
              borderRadius: "var(--radius-lg)",
              background: isSelected ? "var(--color-primary)" : "transparent",
              border: "1px solid transparent",
              cursor: "pointer",
              minWidth: 48,
              transition: "all 150ms",
              position: "relative",
            }}
          >
            <span style={{
              fontSize: "0.6875rem",
              fontWeight: 600,
              textTransform: "uppercase",
              color: isSelected ? "#fff" : "var(--color-text-faint)",
              letterSpacing: "0.05em",
            }}>
              {d.toLocaleDateString("en-US", { weekday: "short" })}
            </span>
            <span style={{
              fontSize: "1.125rem",
              fontWeight: isToday ? 700 : 500,
              color: isSelected ? "#fff" : "var(--color-text)",
              marginTop: 4,
            }}>
              {d.getDate()}
            </span>
            {isToday && !isSelected && (
              <span style={{
                position: "absolute",
                bottom: 4,
                width: 4,
                height: 4,
                borderRadius: "50%",
                background: "var(--color-primary)",
              }} />
            )}
            <div style={{ display: "flex", gap: "2px", marginTop: "4px", height: "4px" }}>
              {Array.from({ length: Math.min(3, weekCounts[d.toISOString().split("T")[0]] || 0) }).map((_, i) => (
                <span key={i} style={{
                  width: 4, height: 4, borderRadius: "50%",
                  background: isSelected ? "#fff" : "var(--color-primary)",
                  opacity: isSelected ? 1 : 0.4,
                }} />
              ))}
            </div>
          </button>
        );
      })}
    </div>
  );
}

/* ── Main Page ─────────────────────────────────────────────── */
export default function SchedulePage() {
  const supabase = useMemo(() => createClient(), []);
  const [selectedDate, setSelectedDate] = useState(() => {
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    return d;
  });
  const [events, setEvents] = useState<CalEvent[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [weekCounts, setWeekCounts] = useState<Record<string, number>>({});
  const [newTaskTitle, setNewTaskTitle] = useState("");

  useEffect(() => {
    let cancelled = false;

    const fetchData = async () => {
      setLoading(true);
      const { data: { user } } = await supabase.auth.getUser();
      if (!user || cancelled) return;

      const startOfDay = new Date(selectedDate);
      startOfDay.setHours(0, 0, 0, 0);
      const endOfDay = new Date(selectedDate);
      endOfDay.setHours(23, 59, 59, 999);
      
      const dateStr = startOfDay.toISOString().split("T")[0];

      const pEvents = supabase
        .from("calendar_events")
        .select("*")
        .eq("user_id", user.id)
        .gte("start_time", startOfDay.toISOString())
        .lte("start_time", endOfDay.toISOString())
        .order("start_time", { ascending: true });

      const pTasks = supabase
        .from("tasks")
        .select("id, title, due_date, status, priority")
        .eq("user_id", user.id)
        .lte("due_date", dateStr)
        .not("due_date", "is", null)
        .neq("status", "done")
        .eq("is_archived", false)
        .order("due_date", { ascending: true });

      const weekStart = getMonday(new Date());
      const weekEnd = new Date(weekStart);
      weekEnd.setDate(weekEnd.getDate() + 6);
      weekEnd.setHours(23, 59, 59, 999);

      const pWeekEvents = supabase
        .from("calendar_events")
        .select("start_time")
        .eq("user_id", user.id)
        .gte("start_time", weekStart.toISOString())
        .lte("start_time", weekEnd.toISOString());

      const pWeekTasks = supabase
        .from("tasks")
        .select("due_date")
        .eq("user_id", user.id)
        .gte("due_date", weekStart.toISOString().split("T")[0])
        .lte("due_date", weekEnd.toISOString().split("T")[0])
        .neq("status", "done")
        .eq("is_archived", false);

      const [resEvents, resTasks, resWeekEvents, resWeekTasks] = await Promise.all([pEvents, pTasks, pWeekEvents, pWeekTasks]);

      if (!cancelled) {
        setEvents(resEvents.data || []);
        setTasks(resTasks.data || []);
        
        const counts: Record<string, number> = {};
        (resWeekEvents.data || []).forEach((e) => {
          const d = e.start_time.split("T")[0];
          counts[d] = (counts[d] || 0) + 1;
        });
        (resWeekTasks.data || []).forEach((t) => {
          const d = t.due_date;
          if (d) counts[d] = (counts[d] || 0) + 1;
        });
        setWeekCounts(counts);
        
        setLoading(false);
      }
    };

    void fetchData();

    let channelEvents: ReturnType<typeof supabase.channel> | null = null;
    let channelTasks: ReturnType<typeof supabase.channel> | null = null;

    const setupRealtime = async () => {
      if (cancelled) return;
      const { data: { session } } = await supabase.auth.getSession();
      if (cancelled) return;
      if (session?.access_token) {
        await supabase.realtime.setAuth(session.access_token);
      }

      channelEvents = supabase.channel("calendar_events_changes")
        .on(
          "postgres_changes",
          { event: "*", schema: "public", table: "calendar_events" },
          () => { if (!cancelled) void fetchData(); }
        )
        .on('system', { event: 'disconnect' }, () => {
          setTimeout(() => { if (!cancelled) setupRealtime(); }, 3000);
        })
        .subscribe();
        
      channelTasks = supabase.channel("tasks_changes")
        .on(
          "postgres_changes",
          { event: "*", schema: "public", table: "tasks" },
          () => { if (!cancelled) void fetchData(); }
        )
        .subscribe();
    };
    
    void setupRealtime();

    return () => {
      cancelled = true;
      if (channelEvents) supabase.removeChannel(channelEvents);
      if (channelTasks) supabase.removeChannel(channelTasks);
    };
  }, [supabase, selectedDate]);

  const dateLabel = selectedDate.toLocaleDateString("en-US", {
    weekday: "long",
    day: "numeric",
    month: "long",
  });
  
  const handleAddTask = async () => {
    if (!newTaskTitle.trim()) return;
    const { data: { user } } = await supabase.auth.getUser();
    if (!user) return;
    const dateStr = selectedDate.toISOString().split("T")[0];
    const optimisticTask: Task = {
      id: crypto.randomUUID(),
      title: newTaskTitle.trim(),
      due_date: dateStr,
      status: "open",
      priority: 0,
    };
    setTasks(prev => [...prev, optimisticTask]);
    setNewTaskTitle("");
    await supabase.from("tasks").insert({
      user_id: user.id,
      title: newTaskTitle.trim(),
      due_date: dateStr,
      status: "open",
      priority: 0,
    });
  };

  const handleCompleteTask = async (taskId: string) => {
    // Optimistic update
    setTasks((prev) => prev.filter(t => t.id !== taskId));
    
    const { data: { user } } = await supabase.auth.getUser();
    if (!user) return;
    
    await supabase
      .from("tasks")
      .update({ status: "done" })
      .eq("id", taskId)
      .eq("user_id", user.id);
  };

  return (
    <div style={{ maxWidth: "800px", margin: "0 auto", padding: "var(--space-8) var(--space-6)", paddingBottom: "100px" }}>
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }
        .skeleton {
          animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
        }
      `}</style>
      <h1 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "var(--space-1)" }}>
        Schedule
      </h1>
      <p style={{
        fontSize: "0.875rem", color: "var(--color-text-muted)",
        marginBottom: "var(--space-6)",
      }}>
        {dateLabel}
      </p>

      <DaySelector selected={selectedDate} onChange={setSelectedDate} weekCounts={weekCounts} />

      {loading ? (
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
          {[1, 2, 3].map((i) => (
            <div key={i} className="skeleton" style={{
              height: "64px",
              background: "var(--color-surface)",
              borderRadius: "var(--radius-lg)",
              border: "1px solid var(--color-border)",
            }} />
          ))}
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-6)" }}>
          <div>
            <div style={{ display: "flex", gap: "var(--space-2)", marginBottom: "var(--space-3)" }}>
              <input
                type="text"
                placeholder="Add task for this day..."
                value={newTaskTitle}
                onChange={e => setNewTaskTitle(e.target.value)}
                onKeyDown={e => { if (e.key === "Enter") void handleAddTask(); }}
                style={{
                  flex: 1,
                  background: "var(--color-surface)",
                  border: "1px solid var(--color-border)",
                  borderRadius: "var(--radius-md)",
                  padding: "var(--space-2) var(--space-3)",
                  color: "var(--color-text)",
                  fontSize: "0.875rem",
                  outline: "none",
                }}
              />
            </div>

            {(events.length === 0 && tasks.length === 0) ? (
              <div style={{
                padding: "var(--space-6)", textAlign: "center",
                borderRadius: "var(--radius-lg)",
                border: "1px dashed var(--color-border)",
                display: "flex", flexDirection: "column", gap: "var(--space-1)",
              }}>
                <span style={{ color: "var(--color-text-muted)", fontSize: "0.875rem" }}>
                  Nothing scheduled
                </span>
                <span style={{ color: "var(--color-text-faint)", fontSize: "0.75rem" }}>
                  Enjoy the free time
                </span>
              </div>
            ) : (
              <>
                {tasks.length > 0 && (
                  <div style={{ marginBottom: "var(--space-6)" }}>
                    <h2 style={{ fontSize: "0.75rem", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--color-text-faint)", marginBottom: "var(--space-3)", marginLeft: "2px" }}>
                      Tasks due
                    </h2>
                    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
                      {tasks.map(task => (
                        <div key={task.id} style={{
                          background: "var(--color-surface)",
                          borderRadius: "var(--radius-lg)",
                          padding: "var(--space-4) var(--space-5)",
                          border: "1px solid var(--color-border)",
                          borderLeft: "3px solid var(--color-warning, #e8a020)",
                          display: "flex",
                          alignItems: "center",
                          gap: "var(--space-3)"
                        }}>
                          <button
                            onClick={() => void handleCompleteTask(task.id)}
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
                              cursor: "pointer",
                            }}
                          />
                          <div style={{ display: "flex", flexDirection: "column", gap: "2px" }}>
                            <div style={{ fontSize: "1rem", fontWeight: 500, color: "var(--color-text)" }}>
                              {task.title}
                            </div>
                            <div style={{ fontSize: "0.8125rem", color: "var(--color-text-muted)" }}>
                              Due today
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {events.length > 0 && (
                  <div>
                    <h2 style={{ fontSize: "0.75rem", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--color-text-faint)", marginBottom: "var(--space-3)", marginLeft: "2px" }}>
                      Schedule
                    </h2>
                    <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
                      {events.map((event) => (
                        <div key={event.id} style={{
                          background: "var(--color-surface)",
                          borderRadius: "var(--radius-lg)",
                          padding: "var(--space-4) var(--space-5)",
                          border: "1px solid var(--color-border)",
                          borderLeft: "3px solid var(--color-primary)",
                          display: "flex",
                          flexDirection: "column",
                          gap: "var(--space-2)"
                        }}>
                          <div style={{ fontSize: "1rem", fontWeight: 500, color: "var(--color-text)" }}>
                            {event.title}
                          </div>
                          <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-4)", fontSize: "0.8125rem", color: "var(--color-text-muted)" }}>
                            <span style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                              {isAllDay(event.start_time) && isAllDay(event.end_time)
                                ? <span>🗓 All day</span>
                                : <span>{formatTime(event.start_time)} – {formatTime(event.end_time)}</span>
                              }
                            </span>
                            {event.calendar_name && (
                              <span style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                                {event.calendar_name}
                              </span>
                            )}
                            {event.location && (
                              <span style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                                {event.location}
                              </span>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
