"use client";

import { useEffect, useMemo, useState } from "react";
import { createClient } from "@/lib/supabase/client";

type CalEvent = {
  id: string;
  summary: string;
  start: string;
  end: string;
  location?: string;
  allDay: boolean;
};

type Briefing = {
  id: string;
  content: string;
  sections: string | null;
  briefing_date: string;
};

const HOUR_HEIGHT = 48; // px per hour
const HOURS = Array.from({ length: 18 }, (_, i) => i + 6); // 6am–11pm

/* ── Helpers ───────────────────────────────────────────────── */
function parseTime(iso: string): { hour: number; minute: number } {
  const d = new Date(iso);
  return { hour: d.getHours(), minute: d.getMinutes() };
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString("en-AU", { hour: "2-digit", minute: "2-digit", hour12: true });
}

function durationMinutes(start: string, end: string): number {
  return Math.max(30, (new Date(end).getTime() - new Date(start).getTime()) / 60000);
}

/* ── Day Selector ──────────────────────────────────────────── */
function DaySelector({ selected, onChange }: {
  selected: Date;
  onChange: (d: Date) => void;
}) {
  const days: Date[] = [];
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  for (let i = -1; i <= 5; i++) {
    const d = new Date(today);
    d.setDate(today.getDate() + i);
    days.push(d);
  }

  return (
    <div style={{
      display: "flex", gap: "var(--space-1)",
      marginBottom: "var(--space-5)",
      overflowX: "auto",
      paddingBottom: "var(--space-1)",
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
              borderRadius: "var(--radius-md)",
              border: isSelected ? "1px solid var(--color-primary)" : "1px solid transparent",
              background: isSelected ? "var(--color-primary-faint)" : "transparent",
              cursor: "pointer",
              minWidth: 44,
              transition: "all 150ms",
            }}
          >
            <span style={{
              fontSize: "0.625rem",
              fontWeight: 500,
              textTransform: "uppercase",
              color: isSelected ? "var(--color-primary)" : "var(--color-text-faint)",
              letterSpacing: "0.05em",
            }}>
              {d.toLocaleDateString("en-AU", { weekday: "short" })}
            </span>
            <span style={{
              fontSize: "1rem",
              fontWeight: isToday ? 700 : 400,
              color: isSelected ? "var(--color-primary)" : "var(--color-text)",
              marginTop: 2,
            }}>
              {d.getDate()}
            </span>
          </button>
        );
      })}
    </div>
  );
}

/* ── Event Block ───────────────────────────────────────────── */
function EventBlock({ event }: { event: CalEvent }) {
  if (event.allDay) return null; // rendered separately

  const { hour, minute } = parseTime(event.start);
  const duration = durationMinutes(event.start, event.end);
  const top = (hour - 6) * HOUR_HEIGHT + (minute / 60) * HOUR_HEIGHT;
  const height = Math.max(24, (duration / 60) * HOUR_HEIGHT);

  return (
    <div style={{
      position: "absolute",
      top, left: 52, right: 8,
      height,
      background: "var(--color-primary-faint)",
      borderLeft: "3px solid var(--color-primary)",
      borderRadius: "var(--radius-sm)",
      padding: "var(--space-1) var(--space-2)",
      overflow: "hidden",
      zIndex: 2,
    }}>
      <div style={{
        fontSize: "0.75rem", fontWeight: 500,
        color: "var(--color-text)",
        whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
      }}>
        {event.summary}
      </div>
      {height > 30 && (
        <div style={{
          fontSize: "0.625rem",
          color: "var(--color-text-muted)",
          marginTop: 1,
        }}>
          {formatTime(event.start)} – {formatTime(event.end)}
          {event.location && ` · ${event.location}`}
        </div>
      )}
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
  const [briefing, setBriefing] = useState<Briefing | null>(null);
  const [loading, setLoading] = useState(true);

  // Parse schedule section from daily briefing
  useEffect(() => {
    let cancelled = false;
    const dateStr = selectedDate.toISOString().split("T")[0];

    const fetch = async () => {
      setLoading(true);

      // Try to get today's briefing for schedule data
      const { data: briefingData } = await supabase
        .from("daily_briefings")
        .select("id,content,sections,briefing_date")
        .eq("briefing_date", dateStr)
        .maybeSingle();

      if (!cancelled && briefingData) {
        setBriefing(briefingData as Briefing);

        // Try to parse structured events from sections
        if (briefingData.sections) {
          try {
            const sections = typeof briefingData.sections === "string"
              ? JSON.parse(briefingData.sections)
              : briefingData.sections;
            const schedule = sections?.schedule || "";
            // Parse events from the schedule text (format: "YYYY-MM-DD HH:MM — Title (Calendar)")
            const parsed: CalEvent[] = [];
            const lines = schedule.split("\n").filter((l: string) => l.trim());
            for (const line of lines) {
              const match = line.match(/^(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})\s+—\s+(.+?)(?:\s+\(.+\))?$/);
              if (match) {
                const [, date, time, title] = match;
                const start = `${date}T${time}:00`;
                // Assume 1 hour default duration
                const startDate = new Date(start);
                const endDate = new Date(startDate.getTime() + 3600000);
                parsed.push({
                  id: `${date}-${time}-${title}`,
                  summary: title,
                  start,
                  end: endDate.toISOString(),
                  allDay: false,
                });
              }
            }
            if (parsed.length > 0) setEvents(parsed);
          } catch {
            // sections not parseable, leave events empty
          }
        }
      }

      setLoading(false);
    };

    void fetch();
    return () => { cancelled = true; };
  }, [supabase, selectedDate]);

  const allDayEvents = events.filter((e) => e.allDay);
  const timedEvents = events.filter((e) => !e.allDay);

  // Current time indicator position
  const now = new Date();
  const isToday = selectedDate.toDateString() === now.toDateString();
  const nowMinutes = now.getHours() * 60 + now.getMinutes();
  const nowTop = ((now.getHours() - 6) * 60 + now.getMinutes()) / 60 * HOUR_HEIGHT;

  const dateLabel = selectedDate.toLocaleDateString("en-AU", {
    weekday: "long",
    day: "numeric",
    month: "long",
  });

  return (
    <div style={{ maxWidth: "800px", margin: "0 auto", padding: "var(--space-6) var(--space-5)" }}>
      <h1 style={{ fontSize: "1.125rem", fontWeight: 600, marginBottom: "var(--space-1)" }}>
        Schedule
      </h1>
      <p style={{
        fontSize: "0.8125rem", color: "var(--color-text-muted)",
        marginBottom: "var(--space-4)",
      }}>
        {dateLabel}
      </p>

      <DaySelector selected={selectedDate} onChange={setSelectedDate} />

      {/* All-day events */}
      {allDayEvents.length > 0 && (
        <div style={{
          marginBottom: "var(--space-3)",
          display: "flex", flexDirection: "column", gap: "var(--space-1)",
        }}>
          {allDayEvents.map((e) => (
            <div key={e.id} style={{
              background: "var(--color-primary-faint)",
              borderRadius: "var(--radius-sm)",
              padding: "var(--space-2) var(--space-3)",
              fontSize: "0.75rem", fontWeight: 500,
              color: "var(--color-primary)",
            }}>
              {e.summary}
            </div>
          ))}
        </div>
      )}

      {/* Timeline */}
      {loading ? (
        <p style={{ color: "var(--color-text-faint)", fontSize: "0.8125rem" }}>Loading…</p>
      ) : events.length === 0 ? (
        <div style={{
          padding: "var(--space-8)", textAlign: "center",
          borderRadius: "var(--radius-lg)",
          border: "1px dashed var(--color-border)",
          color: "var(--color-text-faint)", fontSize: "0.8125rem",
        }}>
          {briefing
            ? "No events parsed from today's briefing."
            : "No briefing yet for this day. Calendar events will appear after the morning briefing runs."}
        </div>
      ) : (
        <div style={{
          position: "relative",
          height: HOURS.length * HOUR_HEIGHT,
          overflow: "hidden",
        }}>
          {/* Hour lines */}
          {HOURS.map((h) => (
            <div key={h} style={{
              position: "absolute",
              top: (h - 6) * HOUR_HEIGHT,
              left: 0, right: 0,
              display: "flex", alignItems: "flex-start",
            }}>
              <span style={{
                width: 44,
                fontSize: "0.625rem",
                color: "var(--color-text-faint)",
                textAlign: "right",
                paddingRight: "var(--space-2)",
                fontFamily: "var(--font-mono)",
                lineHeight: "1",
              }}>
                {h === 0 ? "12am" : h === 12 ? "12pm" : h > 12 ? `${h - 12}pm` : `${h}am`}
              </span>
              <div style={{
                flex: 1,
                borderTop: "1px solid var(--color-border)",
                height: 0,
              }} />
            </div>
          ))}

          {/* Now indicator */}
          {isToday && nowMinutes >= 360 && nowMinutes <= 1380 && (
            <div style={{
              position: "absolute",
              top: nowTop,
              left: 44, right: 0,
              height: 2,
              background: "var(--color-danger)",
              zIndex: 3,
              borderRadius: 1,
            }}>
              <div style={{
                position: "absolute",
                left: -3, top: -3,
                width: 8, height: 8,
                borderRadius: "50%",
                background: "var(--color-danger)",
              }} />
            </div>
          )}

          {/* Events */}
          {timedEvents.map((event) => (
            <EventBlock key={event.id} event={event} />
          ))}
        </div>
      )}
    </div>
  );
}
