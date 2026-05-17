"use client";

import { useEffect, useMemo, useState } from "react";
import { createClient } from "@/lib/supabase/client";

const ONLINE_THRESHOLD_MS = 2 * 60 * 1000;
const POLL_INTERVAL_MS = 30 * 1000;

type HeartbeatRow = {
  last_seen: string | null;
};

export default function DashboardPage() {
  const supabase = useMemo(() => createClient(), []);
  const [online, setOnline] = useState(false);
  const [loading, setLoading] = useState(true);

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

      const row = data as HeartbeatRow;
      if (!row.last_seen) {
        setOnline(false);
      } else {
        const age = Date.now() - new Date(row.last_seen).getTime();
        setOnline(age >= 0 && age <= ONLINE_THRESHOLD_MS);
      }
      setLoading(false);
    };

    void fetchHeartbeat();
    const interval = setInterval(() => {
      void fetchHeartbeat();
    }, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [supabase]);

  const dotColor = online
    ? "var(--color-success, #10b981)"
    : "var(--color-text-muted)";
  const statusText = loading
    ? "Checking worker status…"
    : online
      ? "Mac worker online"
      : "Mac worker offline";

  return (
    <div style={{ maxWidth: "800px", margin: "0 auto", padding: "2rem 1.5rem" }}>
      <h1 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "0.25rem" }}>
        Dashboard
      </h1>
      <p
        style={{
          fontSize: "0.875rem",
          color: "var(--color-text-muted)",
          marginBottom: "1.5rem",
        }}
      >
        Coming in Phase 4 — activity overview, worker status, and usage metrics.
      </p>

      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "0.625rem",
          padding: "0.875rem 1rem",
          background: "var(--color-surface-2)",
          border: "1px solid var(--color-border)",
          borderRadius: "var(--radius-lg)",
        }}
      >
        <span
          aria-hidden
          style={{
            width: "0.5rem",
            height: "0.5rem",
            borderRadius: "50%",
            background: dotColor,
            flexShrink: 0,
            boxShadow: online ? `0 0 6px ${dotColor}` : "none",
          }}
        />
        <span style={{ fontSize: "0.875rem", color: "var(--color-text)" }}>
          {statusText}
        </span>
      </div>
    </div>
  );
}
