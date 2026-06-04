"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
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
  if (a.status === "executed")  return { text: "Executed", bg: "var(--color-success)", color: "#fff" };
  if (a.status === "failed")    return { text: "Failed",   bg: "var(--color-danger)",  color: "#fff" };
  if (a.status === "denied")    return { text: "Denied",   bg: "var(--color-text-faint)", color: "var(--color-bg)" };
  if (a.status === "approved" || a.status === "processing")
    return { text: "Running", bg: "var(--color-primary)", color: "#fff" };
  if (a.status === "awaiting_approval")
    return { text: "Pending", bg: "var(--color-surface-offset)", color: "var(--color-text-muted)" };
  return { text: a.status, bg: "var(--color-surface-offset)", color: "var(--color-text-muted)" };
}

/* ── Collapsible payload viewer ────────────────────────── */
function PayloadView({ action_type, payload }: { action_type: string; payload: Record<string, unknown> }) {
  const [open, setOpen] = useState(false);
  const json = JSON.stringify(payload, null, 2);
  const preview = JSON.stringify(payload);
  const isLong = preview.length > 80;

  if (action_type === "gmail_draft") {
    return (
      <div style={{ background: "var(--color-surface-2)", borderRadius: "var(--radius-md)", padding: "var(--space-3) var(--space-4)", fontSize: "0.875rem", color: "var(--color-text)", border: "1px solid var(--color-border)", marginBottom: "var(--space-3)" }}>
        <div style={{ marginBottom: "var(--space-2)" }}><strong style={{color:"var(--color-text-muted)"}}>To:</strong> {String(payload.to || "")}</div>
        <div style={{ marginBottom: "var(--space-3)" }}><strong style={{color:"var(--color-text-muted)"}}>Subject:</strong> {String(payload.subject || "")}</div>
        <div style={{ whiteSpace: "pre-wrap", color: "var(--color-text-muted)", fontSize: "0.8125rem", background: "var(--color-surface)", padding: "var(--space-3)", borderRadius: "var(--radius-sm)", border: "1px solid var(--color-border-subtle)" }}>{String(payload.body || "")}</div>
      </div>
    );
  }
  
  if (action_type === "calendar_create") {
    return (
      <div style={{ background: "var(--color-surface-2)", borderRadius: "var(--radius-md)", padding: "var(--space-3) var(--space-4)", fontSize: "0.875rem", color: "var(--color-text)", border: "1px solid var(--color-border)", marginBottom: "var(--space-3)" }}>
        <div style={{ marginBottom: "var(--space-2)", fontSize: "1rem", fontWeight: 600 }}>{String(payload.summary || "")}</div>
        <div style={{ color: "var(--color-text-muted)", marginBottom: "var(--space-1)", display: "flex", gap: "var(--space-2)", alignItems: "center" }}>
          <span>🗓️</span> <span>{new Date(String(payload.start || "")).toLocaleString([], {weekday: 'short', month: 'short', day: 'numeric', hour: '2-digit', minute:'2-digit'})}</span>
        </div>
        {!!payload.location && <div style={{ color: "var(--color-text-muted)", marginBottom: "var(--space-1)", display: "flex", gap: "var(--space-2)", alignItems: "center" }}><span>📍</span> <span>{String(payload.location)}</span></div>}
        {!!payload.description && <div style={{ color: "var(--color-text-muted)", whiteSpace: "pre-wrap", marginTop: "var(--space-3)", fontSize: "0.8125rem", borderTop: "1px dashed var(--color-border)", paddingTop: "var(--space-2)" }}>{String(payload.description)}</div>}
      </div>
    );
  }


  return (
    <div style={{ marginBottom: "var(--space-3)" }}>
      {isLong ? (
        <details open={open} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
          <summary style={{
            fontSize: "0.75rem",
            color: "var(--color-text-faint)",
            cursor: "pointer",
            marginBottom: "var(--space-2)",
            userSelect: "none",
          }}>
            {open ? "Hide payload" : "Show payload"}
          </summary>
          <pre style={preStyle}>{json}</pre>
        </details>
      ) : (
        <pre style={preStyle}>{json}</pre>
      )}
    </div>
  );
}

const preStyle: React.CSSProperties = {
  background: "var(--color-surface-2)",
  borderRadius: "var(--radius-md)",
  padding: "var(--space-3) var(--space-4)",
  fontSize: "0.8125rem",
  color: "var(--color-text-muted)",
  overflowX: "auto",
  whiteSpace: "pre-wrap",
  lineHeight: 1.5,
  fontFamily: "var(--font-mono)",
  margin: 0,
};

const btnBase: React.CSSProperties = {
  padding: "var(--space-2) var(--space-5)",
  borderRadius: "var(--radius-md)",
  fontSize: "0.8125rem",
  fontWeight: 500,
  cursor: "pointer",
  transition: "opacity 150ms",
};

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

  const approveById = useCallback(async (id: string) => {
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
  }, []);

  useEffect(() => {
    if (!armed) return;
    if (now >= armed.expiresAt) {
      const id = armed.id;
      setArmed(null);
      void approveById(id);
    }
  }, [armed, now, approveById]);

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

  const pending = actions.filter((a) => a.status === "awaiting_approval");
  const resolved = actions.filter((a) => a.status !== "awaiting_approval");

  return (
    <div style={{ maxWidth: "800px", margin: "0 auto", padding: "var(--space-8) var(--space-5)" }}>
      <h1 style={{ fontSize: "1.125rem", fontWeight: 600, marginBottom: "var(--space-1)" }}>
        Approval Queue
      </h1>
      <p style={{
        fontSize: "0.8125rem", color: "var(--color-text-muted)",
        marginBottom: "var(--space-6)",
      }}>
        Actions execute only after your approval.
      </p>

      {error && (
        <div style={{
          padding: "var(--space-3) var(--space-4)", marginBottom: "var(--space-4)",
          background: "rgba(196, 77, 77, 0.08)", borderRadius: "var(--radius-md)",
          color: "var(--color-danger)", fontSize: "0.8125rem",
        }}>
          {error}
        </div>
      )}

      <section style={{ marginBottom: "var(--space-10)" }}>
        <h2 style={{
          fontSize: "0.6875rem", fontWeight: 600, letterSpacing: "0.08em",
          textTransform: "uppercase", color: "var(--color-text-faint)",
          marginBottom: "var(--space-4)",
        }}>
          Pending {pending.length > 0 && `(${pending.length})`}
        </h2>

        {loading && <p style={{ color: "var(--color-text-faint)", fontSize: "0.8125rem" }}>Loading…</p>}

        {!loading && pending.length === 0 && (
          <div style={{
            padding: "var(--space-8)", textAlign: "center",
            borderRadius: "var(--radius-lg)",
            border: "1px dashed var(--color-border)",
            color: "var(--color-text-faint)", fontSize: "0.8125rem",
          }}>
            No pending actions — all clear.
          </div>
        )}

        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
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
                padding: "var(--space-4) var(--space-5)",
              }}>
                {/* Header */}
                <div style={{
                  display: "flex", alignItems: "center", gap: "var(--space-2)",
                  marginBottom: "var(--space-3)", flexWrap: "wrap",
                }}>
                  <span style={{
                    fontSize: "0.625rem", fontWeight: 600,
                    padding: "2px var(--space-2)", borderRadius: "9999px",
                    background: ACTION_TIER_COLORS[action.tier],
                    color: "#fff", letterSpacing: "0.06em", textTransform: "uppercase",
                  }}>
                    {action.tier}
                  </span>
                  <span style={{ fontSize: "0.875rem", fontWeight: 500 }}>{typeLabel}</span>
                  <span style={{
                    fontSize: "0.6875rem", color: "var(--color-text-faint)", marginLeft: "auto",
                    fontFamily: "var(--font-mono)",
                  }}>
                    {new Date(action.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                  </span>
                </div>

                {/* Payload */}
                <PayloadView action_type={action.action_type} payload={action.payload} />

                {/* Actions */}
                <div style={{ display: "flex", gap: "var(--space-2)", justifyContent: "flex-end" }}>
                  {isArmed ? (
                    <>
                      <button onClick={() => setArmed(null)} style={{
                        ...btnBase,
                        border: "1px solid var(--color-border)", background: "transparent",
                        color: "var(--color-text)",
                      }}>Cancel</button>
                      <button disabled style={{
                        ...btnBase,
                        background: "var(--color-danger)", border: "none",
                        color: "#fff", cursor: "not-allowed", fontVariantNumeric: "tabular-nums",
                      }}>Executing in {remaining}s…</button>
                    </>
                  ) : (
                    <>
                      <button
                        disabled={acting === action.id}
                        onClick={() => denyById(action.id)}
                        style={{
                          ...btnBase,
                          border: "1px solid var(--color-border)", background: "transparent",
                          color: "var(--color-text-muted)",
                          opacity: acting === action.id ? 0.5 : 1,
                          cursor: acting === action.id ? "not-allowed" : "pointer",
                        }}>Deny</button>
                      <button
                        disabled={acting === action.id}
                        onClick={() => handleApprove(action)}
                        style={{
                          ...btnBase,
                          background: action.tier === "hold" ? "var(--color-danger)" : "var(--color-primary)",
                          border: "none", color: "#fff",
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
            fontSize: "0.6875rem", fontWeight: 600, letterSpacing: "0.08em",
            textTransform: "uppercase", color: "var(--color-text-faint)",
            marginBottom: "var(--space-4)",
          }}>History</h2>
          <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
            {resolved.map((action) => {
              const badge = statusBadge(action);
              const typeLabel = TYPE_LABELS[action.action_type] ?? action.action_type;
              return (
                <div key={action.id} style={{
                  display: "flex", alignItems: "center", gap: "var(--space-3)",
                  padding: "var(--space-3) var(--space-4)",
                  background: "var(--color-surface)",
                  border: "1px solid var(--color-border)",
                  borderLeft: `3px solid ${ACTION_TIER_COLORS[action.tier]}`,
                  borderRadius: "var(--radius-md)", fontSize: "0.8125rem",
                }}>
                  <span style={{ fontWeight: 500, minWidth: "100px", flexShrink: 0 }}>{typeLabel}</span>
                  <span style={{
                    color: "var(--color-text-faint)", flex: 1,
                    overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                    fontFamily: "var(--font-mono)", fontSize: "0.75rem",
                  }}>
                    {JSON.stringify(action.payload).slice(0, 60)}
                  </span>
                  <span style={{
                    fontSize: "0.6875rem", fontWeight: 600,
                    padding: "2px var(--space-2)", borderRadius: "9999px",
                    background: badge.bg, color: badge.color, whiteSpace: "nowrap",
                    flexShrink: 0,
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