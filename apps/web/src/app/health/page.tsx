"use client";

import { useCallback, useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import Link from "next/link";

type HealthLog = {
  id: string;
  log_date: string;
  metric: string;
  value: number;
  source: string;
  created_at: string;
  meal_type: string | null;
  description: string | null;
};

/** Today, in the phone's own timezone. `log_date` is a date, not an instant. */
function localToday(): string {
  const tzOffset = new Date().getTimezoneOffset() * 60000;
  return new Date(Date.now() - tzOffset).toISOString().slice(0, 10);
}

export default function HealthPage() {
  const [supabase] = useState(() => createClient());
  const [logs, setLogs] = useState<HealthLog[]>([]);
  const [userId, setUserId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchLogs = useCallback(async (uid: string) => {
    const { data, error: err } = await supabase
      .from("health_logs")
      .select("*")
      .eq("user_id", uid)
      .eq("log_date", localToday())
      .order("created_at", { ascending: false });
    if (err) setError(err.message);
    else setLogs(data ?? []);
    setLoading(false);
  }, [supabase]);

  useEffect(() => {
    let cancelled = false;

    // Declared inside the effect: react-hooks/set-state-in-effect rejects a
    // setState-containing function called from an effect body, even an async
    // one, and this page had been failing lint on exactly that.
    async function start() {
      const { data: { user } } = await supabase.auth.getUser();
      if (cancelled) return;
      if (!user) {
        setLoading(false);
        return;
      }
      setUserId(user.id);
      await fetchLogs(user.id);
    }

    void start();
    return () => { cancelled = true; };
  }, [supabase, fetchLogs]);

  useEffect(() => {
    if (!userId) return;
    // Scoped to this user's rows. The unfiltered subscription woke this page
    // for every row in the table, which only looked harmless because every
    // row in the table happened to be this user's.
    const channel = supabase.channel("health_logs_changes")
      .on("postgres_changes",
          { event: "*", schema: "public", table: "health_logs",
            filter: `user_id=eq.${userId}` },
          () => { void fetchLogs(userId); })
      .subscribe();
    return () => { void supabase.removeChannel(channel); };
  }, [supabase, userId, fetchLogs]);

  /**
   * One row per (user, day, metric, meal type) — upserted, not inserted.
   *
   * That is the table's actual rule, and it was unenforceable until now:
   * nothing wrote `user_id`, and NULLs are distinct under a unique index, so
   * every insert slipped past the constraint. Writing `user_id` without this
   * change would have made the second glass of water of any day fail.
   *
   * `value` is passed as the new TOTAL rather than a delta, because an upsert
   * replaces and PostgREST cannot express `value = value + n`. The caller
   * computes it from what is already on screen.
   */
  const setLog = async (
    metric: string,
    value: number,
    mealType = "",
  ) => {
    if (!userId) return;
    const { error: err } = await supabase.from("health_logs").upsert(
      {
        user_id: userId,
        log_date: localToday(),
        metric,
        meal_type: mealType,
        value,
        source: "manual",
      },
      { onConflict: "user_id,log_date,metric,meal_type" },
    );
    if (err) {
      setError(err.message);
      return;
    }
    setError(null);
    void fetchLogs(userId); // Optimistic refresh; realtime also catches it.
  };

  const waterToday = logs
    .filter((l) => l.metric === "water")
    .reduce((acc, l) => acc + Number(l.value || 0), 0);

  // A running total for the day, so tapping it ten times reads 2500 ml rather
  // than failing nine times.
  const addWater = () => setLog("water", waterToday + 250);
  // Idempotent by design: tapping Lunch twice means the same lunch, not an
  // error and not a second one.
  const logMeal = (meal_type: string) => setLog("meal", 0, meal_type);

  const meals = logs.filter((l) => l.metric === "meal");

  return (
    <div style={{ padding: "var(--space-6) var(--space-5)", maxWidth: "800px", margin: "0 auto", paddingBottom: "100px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "var(--space-4)", marginBottom: "var(--space-6)" }}>
        <Link href="/more" style={{ color: "var(--color-text-muted)", textDecoration: "none" }}>
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="19" y1="12" x2="5" y2="12" />
            <polyline points="12 19 5 12 12 5" />
          </svg>
        </Link>
        <h1 style={{ fontSize: "1.25rem", fontWeight: 600, margin: 0 }}>Health Dashboard</h1>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-6)" }}>
        {/* Quick Actions */}
        <section>
          <h2 style={{ fontSize: "0.9375rem", color: "var(--color-text-muted)", marginBottom: "var(--space-3)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Quick Log</h2>
          <div style={{ display: "flex", gap: "var(--space-3)", flexWrap: "wrap" }}>
            <button onClick={addWater} style={btnStyle}>💧 Add 250ml Water</button>
            <button onClick={() => logMeal("breakfast")} style={btnStyle}>🍳 Breakfast</button>
            <button onClick={() => logMeal("lunch")} style={btnStyle}>🥗 Lunch</button>
            <button onClick={() => logMeal("dinner")} style={btnStyle}>🍽️ Dinner</button>
            <button onClick={() => logMeal("snack")} style={btnStyle}>🍎 Snack</button>
          </div>
        </section>

        {/* Today's Summary */}
        <section>
          <h2 style={{ fontSize: "0.9375rem", color: "var(--color-text-muted)", marginBottom: "var(--space-3)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Today&apos;s Summary</h2>
          {error && (
            <p style={{ fontSize: "0.8125rem", color: "var(--color-danger)", margin: "0 0 var(--space-3)" }}>
              {error}
            </p>
          )}
          {loading && logs.length === 0 ? (
            <div style={{ color: "var(--color-text-faint)" }}>Loading...</div>
          ) : (
            <div style={{ display: "grid", gap: "var(--space-3)" }}>
              <div style={cardStyle}>
                <div style={{ fontSize: "1.75rem", padding: "var(--space-2)" }}>💧</div>
                <div>
                  <div style={{ fontWeight: 600, fontSize: "1.125rem", color: "var(--color-text)" }}>{waterToday} ml</div>
                  <div style={{ fontSize: "0.8125rem", color: "var(--color-text-muted)", marginTop: "2px" }}>Total Water Logged</div>
                </div>
              </div>

              <div style={cardStyle}>
                <div style={{ fontSize: "1.75rem", padding: "var(--space-2)" }}>🍽️</div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600, fontSize: "1.125rem", color: "var(--color-text)" }}>Meals</div>
                  <div style={{ fontSize: "0.8125rem", color: "var(--color-text-muted)", marginTop: "2px", textTransform: "capitalize" }}>
                    {meals.length > 0 ? meals.map(m => m.meal_type).join(", ") : "No meals logged yet"}
                  </div>
                </div>
              </div>
            </div>
          )}
        </section>

        {/* Recent Logs */}
        <section>
          <h2 style={{ fontSize: "0.9375rem", color: "var(--color-text-muted)", marginBottom: "var(--space-3)", textTransform: "uppercase", letterSpacing: "0.05em" }}>Timeline</h2>
          <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
            {logs.map((log) => {
              const time = new Date(log.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
              let label = log.metric;
              let icon = "📝";
              if (log.metric === "water") {
                label = `Water (${log.value}ml)`;
                icon = "💧";
              }
              if (log.metric === "meal") {
                label = `Meal (${log.meal_type})`;
                icon = "🍽️";
              }
              
              return (
                <div key={log.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "var(--space-3) var(--space-4)", background: "var(--color-surface)", borderRadius: "var(--radius-lg)", border: "1px solid var(--color-border)" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "var(--space-3)" }}>
                    <span style={{ fontSize: "1.125rem" }}>{icon}</span>
                    <span style={{ fontSize: "0.9375rem", color: "var(--color-text)", textTransform: "capitalize" }}>{label}</span>
                  </div>
                  <span style={{ fontSize: "0.8125rem", color: "var(--color-text-muted)", fontWeight: 500 }}>{time}</span>
                </div>
              )
            })}
            {logs.length === 0 && !loading && (
              <div style={{ color: "var(--color-text-faint)", fontSize: "0.875rem", textAlign: "center", padding: "var(--space-6) 0", background: "var(--color-surface)", borderRadius: "var(--radius-lg)", border: "1px dashed var(--color-border)" }}>
                No activity logged today.
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

const btnStyle = {
  padding: "var(--space-3) var(--space-4)",
  background: "var(--color-surface-2)",
  border: "1px solid var(--color-border-strong)",
  borderRadius: "var(--radius-xl)",
  color: "var(--color-text)",
  fontSize: "0.875rem",
  fontWeight: 500,
  cursor: "pointer",
  display: "flex",
  alignItems: "center",
  gap: "var(--space-2)",
  transition: "background 150ms, transform 100ms",
  boxShadow: "var(--shadow-sm)",
};

const cardStyle = {
  padding: "var(--space-4)",
  background: "var(--color-surface)",
  border: "1px solid var(--color-border)",
  borderRadius: "var(--radius-lg)",
  display: "flex",
  alignItems: "center",
  gap: "var(--space-4)",
  boxShadow: "var(--shadow-sm)",
};
