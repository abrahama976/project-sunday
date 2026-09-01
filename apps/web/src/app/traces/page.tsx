"use client";

/**
 * Traces — how Sunday reached an answer.
 *
 * The loop chains up to five tool steps per message, and only the `final` row
 * reaches chat. That is deliberate (a five-step answer should arrive as one
 * message) but it leaves the transcript unable to say what ran, what failed, or
 * why it stopped. `agent_turns` holds every step; this reads it back.
 *
 * Three bounded queries rather than a PostgREST embed: the run index, the
 * termination rows for exactly those runs, and the prompts they came from.
 * The embed would be one query fewer and one silent failure mode more — if the
 * FK ever stopped resolving, the whole page would go blank instead of one
 * label.
 */

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";

/* ── Shapes ─────────────────────────────────────────────── */

const TURN_TYPES = ["thought", "tool_call", "tool_result", "final", "loop_break"] as const;
type TurnType = (typeof TURN_TYPES)[number];

type TurnRow = {
  id: string;
  run_id: string;
  message_id: string | null;
  step_index: number;
  type: TurnType;
  tool_name: string | null;
  args: unknown;
  result: string | null;
  error: string | null;
  model: string | null;
  latency_ms: number | null;
  created_at: string;
};

function isTurnRow(x: unknown): x is TurnRow {
  if (!x || typeof x !== "object") return false;
  const o = x as Record<string, unknown>;
  return (
    typeof o.id === "string" &&
    typeof o.run_id === "string" &&
    typeof o.type === "string" &&
    (TURN_TYPES as readonly string[]).includes(o.type) &&
    typeof o.created_at === "string"
  );
}

const RUN_LIMIT = 25;
const RESULT_CLAMP = 400;

/* ── Formatting ─────────────────────────────────────────── */

function formatWhen(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const sameDay = d.toDateString() === new Date().toDateString();
  return sameDay ? time : `${d.toLocaleDateString([], { day: "numeric", month: "short" })} ${time}`;
}

function formatMs(ms: number | null): string {
  if (ms === null || ms === undefined) return "";
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

/* ── Termination reasons ────────────────────────────────── */
/* The `error` strings agent_loop.py writes on a loop_break row. A run with no
   loop_break row simply ran to an answer. */

type Tone = "ok" | "warn" | "bad";

function terminationLabel(brk: TurnRow | undefined): { text: string; tone: Tone } {
  if (!brk) return { text: "Completed", tone: "ok" };
  const e = (brk.error ?? "").trim();
  if (e === "cap-hit") return { text: "Hit the 5-round cap", tone: "warn" };
  if (e === "no-progress")
    return { text: "Called the same tool twice with identical arguments", tone: "warn" };
  if (e === "write-tier-halt")
    return {
      text: brk.tool_name ? `Queued ${brk.tool_name} for approval` : "Queued a write for approval",
      tone: "ok",
    };
  if (e === "budget-exhausted") return { text: "Daily budget exhausted", tone: "warn" };
  if (e.startsWith("degraded-"))
    return { text: `Degraded to ${e.slice("degraded-".length)} — chat only, no further tools`, tone: "warn" };
  // Anything else is a model error, passed through verbatim.
  return { text: e || "Stopped", tone: "bad" };
}

const TONE_COLOR: Record<Tone, string> = {
  ok: "var(--color-success)",
  warn: "var(--color-warning)",
  bad: "var(--color-danger)",
};

const TONE_BG: Record<Tone, string> = {
  ok: "var(--color-success-faint)",
  warn: "var(--color-warning-faint)",
  bad: "var(--color-danger-faint)",
};

/* ── Long text, clamped ─────────────────────────────────── */

function ClampedText({ text, mono = false }: { text: string; mono?: boolean }) {
  const [open, setOpen] = useState(false);
  const long = text.length > RESULT_CLAMP;
  const shown = open || !long ? text : `${text.slice(0, RESULT_CLAMP)}…`;

  return (
    <div>
      <pre
        style={{
          margin: 0,
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
          fontFamily: mono ? "var(--font-mono)" : "inherit",
          fontSize: mono ? "0.75rem" : "0.8125rem",
          color: "var(--color-text)",
          lineHeight: 1.55,
        }}
      >
        {shown}
      </pre>
      {long && (
        <button
          onClick={() => setOpen((v) => !v)}
          style={{
            marginTop: "var(--space-2)",
            background: "transparent",
            border: "none",
            padding: 0,
            color: "var(--color-primary)",
            fontSize: "0.75rem",
            cursor: "pointer",
          }}
        >
          {open ? "Show less" : `Show all ${text.length.toLocaleString()} characters`}
        </button>
      )}
    </div>
  );
}

/* ── One step ───────────────────────────────────────────── */

const STEP_META: Record<TurnType, { icon: string; label: string }> = {
  thought: { icon: "💭", label: "Thought" },
  tool_call: { icon: "🔧", label: "Called" },
  tool_result: { icon: "📄", label: "Result" },
  loop_break: { icon: "⏹", label: "Stopped" },
  final: { icon: "✓", label: "Answer" },
};

function StepRow({ step }: { step: TurnRow }) {
  const meta = STEP_META[step.type];
  const args =
    step.type === "tool_call" && step.args && typeof step.args === "object"
      ? JSON.stringify(step.args, null, 2)
      : null;

  return (
    <div
      style={{
        display: "flex",
        gap: "var(--space-3)",
        padding: "var(--space-3) 0",
        borderTop: "1px solid var(--color-border)",
      }}
    >
      <span style={{ fontSize: "0.875rem", lineHeight: 1.4, flexShrink: 0, width: "1.25rem" }}>
        {meta.icon}
      </span>

      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            display: "flex",
            alignItems: "baseline",
            gap: "var(--space-2)",
            flexWrap: "wrap",
            marginBottom: "var(--space-2)",
          }}
        >
          <span
            style={{
              fontSize: "0.6875rem",
              fontWeight: 600,
              textTransform: "uppercase",
              letterSpacing: "0.04em",
              color: "var(--color-text-muted)",
            }}
          >
            {meta.label}
          </span>
          {step.tool_name && (
            <span style={{ fontFamily: "var(--font-mono)", fontSize: "0.75rem", color: "var(--color-primary)" }}>
              {step.tool_name}
            </span>
          )}
          {step.latency_ms !== null && (
            <span style={{ fontSize: "0.6875rem", color: "var(--color-text-faint)", marginLeft: "auto" }}>
              {formatMs(step.latency_ms)}
            </span>
          )}
        </div>

        {args && <ClampedText text={args} mono />}

        {step.type === "loop_break" ? (
          <div style={{ fontSize: "0.8125rem", color: TONE_COLOR[terminationLabel(step).tone] }}>
            {terminationLabel(step).text}
          </div>
        ) : (
          <>
            {step.error && (
              <div
                style={{
                  fontFamily: "var(--font-mono)",
                  fontSize: "0.75rem",
                  color: "var(--color-danger)",
                  wordBreak: "break-word",
                }}
              >
                {step.error}
              </div>
            )}
            {step.result && <ClampedText text={step.result} />}
          </>
        )}
      </div>
    </div>
  );
}

/* ── One run ────────────────────────────────────────────── */

function RunCard({
  run,
  prompt,
  breakRow,
}: {
  run: TurnRow;
  prompt: string | null;
  breakRow: TurnRow | undefined;
}) {
  const supabase = useMemo(() => createClient(), []);
  const [open, setOpen] = useState(false);
  const [steps, setSteps] = useState<TurnRow[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reason = terminationLabel(breakRow);

  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (!next || steps || loading) return;

    setLoading(true);
    setError(null);
    // Ordered by created_at, not step_index: several rows share one step index
    // (a tool_call and its tool_result are both step N).
    const { data, error: err } = await supabase
      .from("agent_turns")
      .select("*")
      .eq("run_id", run.run_id)
      .order("created_at", { ascending: true });
    setLoading(false);
    if (err) {
      setError(err.message);
      return;
    }
    setSteps((data ?? []).filter(isTurnRow));
  };

  return (
    <div
      style={{
        background: "var(--color-surface)",
        border: "1px solid var(--color-border)",
        borderRadius: "var(--radius-lg)",
        overflow: "hidden",
      }}
    >
      <button
        onClick={toggle}
        aria-expanded={open}
        style={{
          width: "100%",
          background: "transparent",
          border: "none",
          textAlign: "left",
          padding: "var(--space-4)",
          color: "var(--color-text)",
          cursor: "pointer",
          display: "flex",
          gap: "var(--space-3)",
          alignItems: "flex-start",
        }}
      >
        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              fontSize: "0.9375rem",
              fontWeight: 500,
              overflow: "hidden",
              textOverflow: "ellipsis",
              display: "-webkit-box",
              WebkitLineClamp: 2,
              WebkitBoxOrient: "vertical",
              color: prompt ? "var(--color-text)" : "var(--color-text-faint)",
            }}
          >
            {prompt ?? "(message cleared)"}
          </div>

          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "var(--space-2)",
              flexWrap: "wrap",
              marginTop: "var(--space-2)",
              fontSize: "0.6875rem",
              color: "var(--color-text-faint)",
            }}
          >
            <span
              style={{
                padding: "2px 8px",
                borderRadius: "var(--radius-sm)",
                background: TONE_BG[reason.tone],
                color: TONE_COLOR[reason.tone],
                fontWeight: 500,
              }}
            >
              {reason.text}
            </span>
            <span>{formatWhen(run.created_at)}</span>
            {run.model && run.model !== "system" && <span>{run.model}</span>}
            {run.latency_ms !== null && <span>{formatMs(run.latency_ms)}</span>}
          </div>
        </div>

        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="var(--color-text-faint)"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{
            flexShrink: 0,
            marginTop: 2,
            transform: open ? "rotate(90deg)" : "none",
            transition: "transform 150ms",
          }}
        >
          <polyline points="9 18 15 12 9 6" />
        </svg>
      </button>

      {open && (
        <div style={{ padding: "0 var(--space-4) var(--space-3) var(--space-4)" }}>
          {loading && <div style={{ fontSize: "0.8125rem", color: "var(--color-text-faint)" }}>Loading steps…</div>}
          {error && <div style={{ fontSize: "0.8125rem", color: "var(--color-danger)" }}>{error}</div>}
          {steps?.map((s) => <StepRow key={s.id} step={s} />)}
        </div>
      )}
    </div>
  );
}

/* ── Page ───────────────────────────────────────────────── */

export default function TracesPage() {
  const supabase = useMemo(() => createClient(), []);
  const [runs, setRuns] = useState<TurnRow[]>([]);
  const [breaks, setBreaks] = useState<Record<string, TurnRow>>({});
  const [prompts, setPrompts] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // The loader lives inside the effect on purpose. Lifting it to a useCallback
  // and calling it from the effect trips react-hooks/set-state-in-effect: the
  // rule cannot see past a call boundary to tell that every setState here
  // happens after an await. Refresh re-runs it by bumping `reloadKey`.
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      // Every loop exit writes exactly one `final`, so this IS the list of runs.
      const { data: finals, error: finalsErr } = await supabase
        .from("agent_turns")
        .select("*")
        .eq("type", "final")
        .order("created_at", { ascending: false })
        .limit(RUN_LIMIT);
      if (cancelled) return;

      if (finalsErr) {
        setError(finalsErr.message);
        setLoading(false);
        return;
      }

      const rows = (finals ?? []).filter(isTurnRow);
      if (rows.length === 0) {
        setRuns(rows);
        setLoading(false);
        return;
      }

      const runIds = rows.map((r) => r.run_id);
      const messageIds = Array.from(
        new Set(rows.map((r) => r.message_id).filter((id): id is string => typeof id === "string"))
      );

      // Termination rows for exactly these runs — uses idx_agent_turns_run_id.
      const [{ data: breakRows }, { data: msgRows }] = await Promise.all([
        supabase.from("agent_turns").select("*").eq("type", "loop_break").in("run_id", runIds),
        messageIds.length
          ? supabase.from("messages").select("id, content").in("id", messageIds)
          : Promise.resolve({ data: [] as { id: string; content: string }[] }),
      ]);
      if (cancelled) return;

      const byRun: Record<string, TurnRow> = {};
      for (const row of (breakRows ?? []).filter(isTurnRow)) byRun[row.run_id] = row;

      const byId: Record<string, string> = {};
      for (const m of msgRows ?? []) {
        if (m && typeof m.id === "string" && typeof m.content === "string") byId[m.id] = m.content;
      }

      // Set together: showing the runs before their prompts arrive would flash
      // "(message cleared)" across every card, which reads as data loss.
      setBreaks(byRun);
      setPrompts(byId);
      setRuns(rows);
      setLoading(false);
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [supabase, reloadKey]);

  return (
    <div
      style={{
        padding: "var(--space-6) var(--space-5)",
        maxWidth: "800px",
        margin: "0 auto",
        paddingBottom: "100px",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: "var(--space-4)", marginBottom: "var(--space-2)" }}>
        <Link href="/more" style={{ color: "var(--color-text-muted)", textDecoration: "none" }}>
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="19" y1="12" x2="5" y2="12" />
            <polyline points="12 19 5 12 12 5" />
          </svg>
        </Link>
        <h1 style={{ fontSize: "1.25rem", fontWeight: 600, margin: 0 }}>Traces</h1>
        <button
          onClick={() => {
            setLoading(true);
            setError(null);
            setReloadKey((k) => k + 1);
          }}
          style={{
            marginLeft: "auto",
            background: "transparent",
            border: "1px solid var(--color-border)",
            borderRadius: "var(--radius-md)",
            color: "var(--color-text-muted)",
            fontSize: "0.75rem",
            padding: "var(--space-1) var(--space-3)",
            cursor: "pointer",
          }}
        >
          Refresh
        </button>
      </div>

      <p style={{ fontSize: "0.8125rem", color: "var(--color-text-muted)", marginTop: 0, marginBottom: "var(--space-5)" }}>
        Each answer, and the steps it took to get there.
      </p>

      {error && (
        <div
          style={{
            padding: "var(--space-3) var(--space-4)",
            background: "var(--color-danger-faint)",
            color: "var(--color-danger)",
            borderRadius: "var(--radius-lg)",
            fontSize: "0.8125rem",
            marginBottom: "var(--space-4)",
          }}
        >
          {error}
        </div>
      )}

      {loading && runs.length === 0 && (
        <div style={{ color: "var(--color-text-faint)", fontSize: "0.875rem" }}>Loading…</div>
      )}

      {!loading && runs.length === 0 && !error && (
        <div
          style={{
            color: "var(--color-text-faint)",
            fontSize: "0.875rem",
            textAlign: "center",
            padding: "var(--space-8) var(--space-5)",
            background: "var(--color-surface)",
            borderRadius: "var(--radius-lg)",
            border: "1px dashed var(--color-border)",
            lineHeight: 1.6,
          }}
        >
          No traces yet.
          <br />
          Sunday writes one of these every time it answers.
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
        {runs.map((run) => (
          <RunCard
            key={run.id}
            run={run}
            prompt={run.message_id ? (prompts[run.message_id] ?? null) : null}
            breakRow={breaks[run.run_id]}
          />
        ))}
      </div>
    </div>
  );
}
