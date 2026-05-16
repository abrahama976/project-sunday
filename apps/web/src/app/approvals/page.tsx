"use client";

import { useEffect, useMemo, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { APPROVAL_HOLD_SECONDS, ACTION_TIER_COLORS } from "@/lib/constants";

type Tier = "auto" | "approve" | "hold";

type Action = {
  id: string;
  action_type: string;
  payload: Record<string, unknown>;
  status: string;
  approved: boolean | null;
  tier: Tier;
  error: Record<string, unknown> | null;
  created_at: string;
  approved_at: string | null;
  executed_at: string | null;
};

const TYPE_LABELS: Record<string, string> = {
  file_read: "File Read",
  file_list: "File List",
  file_write: "File Write",
  file_delete: "File Delete",
  calendar_query: "Calendar Read",
  calendar_create: "Calendar Create",
  calendar_delete: "Calendar Delete",
  gmail_search: "Gmail Search",
  gmail_draft: "Gmail Draft",
  gmail_send: "Gmail Send",
  shell_cmd: "Shell",
  update_profile: "Update Profile",
  inventory_update: "Inventory Update",
  web_fetch: "Web Fetch",
};

function isAction(x: unknown): x is Action {
  if (!x || typeof x !== "object") return false;
  const o = x as Record<string, unknown>;
  return typeof o.id === "string" && typeof o.action_type === "string";
}

function statusBadge(a: Action): { text: string; bg: string; color: string } {
  if (a.status === "executed")  return { text: "Executed", bg: "var(--color-success, #10b981)", color: "#fff" };
  if (a.status === "failed")    return { text: "Failed",   bg: "var(--color-danger, #ef4444)",  color: "#fff" };
  if (a.status === "denied")    return { text: "Denied",   bg: "var(--color-text-muted)",       color: "#fff" };
  if (a.status === "approved" || a.status === "executing")
    return { text: "Running", bg: "var(--color-primary)", color: "#fff" };
  return { text: "Pending", bg: "var(--color-surface-offset)", color: "var(--color-text-muted)" };
}

export default function ApprovalsPage() {
  const supabase = useMemo(() => createClient(), []);

  const [actions, setActions] = useState<Action[]>([]);
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [armed, setArmed] = useState<{ id: string; expiresAt: number } | null>(null);
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    let cancelled = false;
    const seen = new Set<string>();

    const channel = supabase
      .channel("action-queue-realtime")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "action_queue" },
        (payload) => {
          if (payload.eventType === "INSERT" && isAction(payload.new)) {
            const row = payload.new;
            if (row.tier === "auto") return;
            if (seen.has(row.id)) return;
            seen.add(row.id);
            setActions((prev) => [row, ...prev]);
          } else if (payload.eventType === "UPDATE" && isAction(payload.new)) {
            const row = payload.new;
            setActions((prev) => prev.map((a) => (a.id === row.id ? row : a)));
          }
        }
      )
      .subscribe();

    (async () => {
      const { data, error: loadErr } = await supabase
        .from("action_queue")
        .select("*")
        .neq("tier", "auto")
        .order("created_at", { ascending: false })
        .limit(50);

      if (cancelled) return;
      if (loadErr) {
        setError(`Failed to load: ${loadErr.message}`);
        setLoading(false);
        return;
      }
      if (data) {
        const rows = (data as unknown[]).filter(isAction);
        rows.forEach((r) => seen.add(r.id));
        setActions(rows);
      }
      setLoading(false);
    })();

    return () => {
      cancelled = true;
      supabase.removeChannel(channel);
    };
  }, [supabase]);

  useEffect(() => {
    if (!armed) return;
    const i = setInterval(() => setNow(Date.now()), 100);
    return () => clearInterval(i);
  }, [armed]);

  useEffect(() => {
    if (!armed) return;
    if (now >= armed.expiresAt) {
      const id = armed.id;
      setArmed(null);
      void approveById(id);
    }
  }, [armed, now]);

  async function approveById(id: string) {
    setActing(id);
    setError(null);
    try {
      const res = await fetch(`/api/actions/${id}/approve`, { method: "POST" });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ error: "request failed" }));
        setError(`Approve failed: ${body.error}`);
      }
    } finally {
      setActing(null);
    }
  }

  async function denyById(id: string) {
    setActing(id);
    setError(null);
    try {
      const res = await fetch(`/api/actions/${id}/deny`, { method: "POST" });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ error: "request failed" }));
        setError(`Deny failed: ${body.error}`);
      }
    } finally {
      setActing(null);
    }
  }

  function handleApprove(action: Action) {
    if (action.tier === "hold") {
      setArmed({ id: action.id, expiresAt: Date.now() + APPROVAL_HOLD_SECONDS * 1000 });
    } else {
      void approveById(action.id);
    }
  }

  const pending = actions.filter((a) => a.status === "pending" && a.approved === null);
  const resolved = actions.filter((a) => a.status !== "pending" || a.approved !== null);

  return (
    <div style={{ maxWidth: "800px", margin: "0 auto", padding: "2rem 1.5rem" }}>
      <h1 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "0.25rem" }}>
        Approval Queue
      </h1>
      <p style={{ fontSize: "0.875rem", color: "var(--color-text-muted)", marginBottom: "1.5rem" }}>
        The Mac worker cannot execute any non-auto action until you approve it here.
      </p>

      {error && (
        <div style={{
          padding: "0.625rem 1rem", marginBottom: "1rem",
          background: "rgba(239,68,68,0.08)", borderRadius: "var(--radius-md, 0.5rem)",
          color: "var(--color-danger, #ef4444)", fontSize: "0.8125rem",
        }}>
          {error}
        </div>
      )}

      <section style={{ marginBottom: "2.5rem" }}>
        <h2 style={{
          fontSize: "0.75rem", fontWeight: 600, letterSpacing: "0.08em",
          textTransform: "uppercase", color: "var(--color-text-faint)", marginBottom: "1rem",
        }}>
          Awaiting your approval {pending.length > 0 && `(${pending.length})`}
        </h2>

        {loading && <p style={{ color: "var(--color-text-faint)", fontSize: "0.875rem" }}>Loading…</p>}

        {!loading && pending.length === 0 && (
          <div style={{
            padding: "2rem", textAlign: "center",
            borderRadius: "var(--radius-lg)",
            background: "var(--color-surface)",
            border: "1px solid var(--color-border)",
            color: "var(--color-text-faint)", fontSize: "0.875rem",
          }}>
            No pending actions — you&apos;re all clear.
          </div>
        )}

        <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
          {pending.map((action) => {
            const typeLabel = TYPE_LABELS[action.action_type] ?? action.action_type;
            const isArmed = armed?.id === action.id;
            const remaining = isArmed ? Math.max(0, Math.ceil((armed.expiresAt - now) / 1000)) : 0;

            return (
              <div key={action.id} style={{
                background: "var(--color-surface)",
                border: "1px solid var(--color-border)",
                borderLeft: `3px solid ${ACTION_TIER_COLORS[action.tier]}`,
                borderRadius: "var(--radius-lg)",
                padding: "1rem 1.25rem",
                boxShadow: "var(--shadow-md)",
              }}>
                <div style={{
                  display: "flex", alignItems: "center", gap: "0.5rem",
                  marginBottom: "0.75rem", flexWrap: "wrap",
                }}>
                  <span style={{
                    fontSize: "0.6875rem", fontWeight: 600,
                    padding: "0.15rem 0.5rem", borderRadius: "9999px",
                    background: ACTION_TIER_COLORS[action.tier],
                    color: "#fff", letterSpacing: "0.06em", textTransform: "uppercase",
                  }}>
                    {action.tier}
                  </span>
                  <span style={{ fontSize: "0.875rem", fontWeight: 500 }}>{typeLabel}</span>
                  <span style={{
                    fontSize: "0.75rem", color: "var(--color-text-faint)", marginLeft: "auto",
                  }}>
                    {new Date(action.created_at).toLocaleTimeString()}
                  </span>
                </div>

                <pre style={{
                  background: "var(--color-surface-2, #201f1d)",
                  borderRadius: "var(--radius-md)",
                  padding: "0.75rem", fontSize: "0.8125rem",
                  color: "var(--color-text-muted)",
                  overflowX: "auto", whiteSpace: "pre-wrap",
                  marginBottom: "1rem", lineHeight: 1.5,
                  fontFamily: "ui-monospace, SFMono-Regular, monospace",
                }}>
                  {JSON.stringify(action.payload, null, 2)}
                </pre>

                <div style={{ display: "flex", gap: "0.5rem", justifyContent: "flex-end" }}>
                  {isArmed ? (
                    <>
                      <button onClick={() => setArmed(null)} style={{
                        padding: "0.5rem 1.25rem", borderRadius: "var(--radius-md)",
                        border: "1px solid var(--color-border)", background: "transparent",
                        fontSize: "0.875rem", color: "var(--color-text)", cursor: "pointer",
                      }}>Cancel</button>
                      <button disabled style={{
                        padding: "0.5rem 1.25rem", borderRadius: "var(--radius-md)",
                        background: "var(--color-danger, #ef4444)", border: "none",
                        fontSize: "0.875rem", fontWeight: 500, color: "#fff",
                        cursor: "not-allowed", fontVariantNumeric: "tabular-nums",
                      }}>Executing in {remaining}s…</button>
                    </>
                  ) : (
                    <>
                      <button
                        disabled={acting === action.id}
                        onClick={() => denyById(action.id)}
                        style={{
                          padding: "0.5rem 1.25rem", borderRadius: "var(--radius-md)",
                          border: "1px solid var(--color-border)", background: "transparent",
                          fontSize: "0.875rem", color: "var(--color-text-muted)",
                          opacity: acting === action.id ? 0.5 : 1,
                          cursor: acting === action.id ? "not-allowed" : "pointer",
                        }}>Deny</button>
                      <button
                        disabled={acting === action.id}
                        onClick={() => handleApprove(action)}
                        style={{
                          padding: "0.5rem 1.25rem", borderRadius: "var(--radius-md)",
                          background: action.tier === "hold"
                            ? "var(--color-danger, #ef4444)"
                            : "var(--color-primary)",
                          border: "none", fontSize: "0.875rem", fontWeight: 500, color: "#fff",
                          opacity: acting === action.id ? 0.5 : 1,
                          cursor: acting === action.id ? "not-allowed" : "pointer",
                        }}>
                        {acting === action.id ? "…" : action.tier === "hold" ? "Approve (hold)" : "Approve"}
                      </button>
                    </>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {resolved.length > 0 && (
        <section>
          <h2 style={{
            fontSize: "0.75rem", fontWeight: 600, letterSpacing: "0.08em",
            textTransform: "uppercase", color: "var(--color-text-faint)", marginBottom: "1rem",
          }}>Recent history</h2>
          <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem" }}>
            {resolved.map((action) => {
              const badge = statusBadge(action);
              const typeLabel = TYPE_LABELS[action.action_type] ?? action.action_type;
              return (
                <div key={action.id} style={{
                  display: "flex", alignItems: "center", gap: "0.75rem",
                  padding: "0.625rem 1rem",
                  background: "var(--color-surface)",
                  border: "1px solid var(--color-border)",
                  borderLeft: `3px solid ${ACTION_TIER_COLORS[action.tier]}`,
                  borderRadius: "var(--radius-md)", fontSize: "0.875rem",
                }}>
                  <span style={{ fontWeight: 500, minWidth: "110px" }}>{typeLabel}</span>
                  <span style={{
                    color: "var(--color-text-muted)", flex: 1,
                    overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                  }}>
                    {JSON.stringify(action.payload).slice(0, 80)}…
                  </span>
                  <span style={{
                    fontSize: "0.75rem", fontWeight: 600,
                    padding: "0.2rem 0.6rem", borderRadius: "9999px",
                    background: badge.bg, color: badge.color, whiteSpace: "nowrap",
                  }}>{badge.text}</span>
                </div>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}