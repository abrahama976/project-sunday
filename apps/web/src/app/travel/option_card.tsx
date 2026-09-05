"use client";

import { useState } from "react";
import {
  Option, Leg, clock, duration, isDriven, STRATEGY_LABELS,
} from "./types";

/**
 * One journey, as a card.
 *
 * The leave time is the largest thing on it, because "when do I need to walk
 * out of the door" is the question almost every trip is really asking. The
 * arrival is second. Everything else — walking, waiting, changes — is the
 * detail you check once you have decided, so it reads as a quiet row rather
 * than competing with the two numbers that matter.
 */

const MODE_TONE: Record<string, string> = {
  Walk: "var(--color-text-muted)",
  Drive: "var(--color-warning)",
  "Dropped off": "var(--color-warning)",
};

function legTone(leg: Leg): string {
  return MODE_TONE[leg.mode] ?? "var(--color-primary)";
}

function LegRow({ leg }: { leg: Leg }) {
  const isMove = leg.mode === "Walk";
  return (
    <li style={{ display: "flex", gap: "var(--space-3)", alignItems: "baseline" }}>
      <span
        style={{
          flexShrink: 0,
          width: "3.25rem",
          fontFamily: "var(--font-mono)",
          fontSize: "0.75rem",
          color: "var(--color-text-faint)",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {clock(leg.depart)}
      </span>
      <span
        aria-hidden
        style={{
          flexShrink: 0,
          width: "0.5rem",
          height: "0.5rem",
          borderRadius: "999px",
          background: legTone(leg),
          opacity: isMove ? 0.5 : 1,
          transform: "translateY(-1px)",
        }}
      />
      <span style={{ fontSize: "0.8125rem", color: "var(--color-text)", minWidth: 0 }}>
        {leg.line ? (
          <strong style={{ color: legTone(leg) }}>
            {leg.mode} {leg.line}
          </strong>
        ) : (
          <span style={{ color: "var(--color-text-muted)" }}>{leg.mode}</span>
        )}
        <span style={{ color: "var(--color-text-muted)" }}>
          {" "}
          {leg.minutes} min{leg.to ? ` → ${leg.to}` : ""}
        </span>
      </span>
    </li>
  );
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1px" }}>
      <span
        style={{
          fontSize: "0.8125rem",
          color: "var(--color-text)",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {value}
      </span>
      <span style={{ fontSize: "0.6875rem", color: "var(--color-text-faint)" }}>
        {label}
      </span>
    </div>
  );
}

export default function OptionCard({
  option,
  best,
  carFreeAnchor,
}: {
  option: Option;
  best: boolean;
  /** True when this is the best option that involves no car at all. */
  carFreeAnchor: boolean;
}) {
  const [open, setOpen] = useState(best);
  const driven = isDriven(option);
  const label = STRATEGY_LABELS[option.strategy ?? ""] ?? "";

  return (
    <div
      style={{
        background: "var(--color-surface)",
        border: `1px solid ${best ? "var(--color-primary)" : "var(--color-border)"}`,
        borderRadius: "var(--radius-lg)",
        padding: "var(--space-4)",
        display: "flex",
        flexDirection: "column",
        gap: "var(--space-3)",
      }}
    >
      <div style={{ display: "flex", alignItems: "flex-start", gap: "var(--space-3)" }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: "0.6875rem", color: "var(--color-text-faint)" }}>
            Leave
          </div>
          <div
            style={{
              fontSize: "1.5rem",
              fontWeight: 600,
              color: "var(--color-text)",
              lineHeight: 1.1,
              fontVariantNumeric: "tabular-nums",
            }}
          >
            {clock(option.depart)}
          </div>
          <div style={{ fontSize: "0.8125rem", color: "var(--color-text-muted)", marginTop: "2px" }}>
            arrive {clock(option.arrive)} · {duration(option.duration_min)}
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-1)", alignItems: "flex-end" }}>
          {best && (
            <span
              style={{
                fontSize: "0.6875rem",
                fontWeight: 600,
                padding: "2px var(--space-2)",
                borderRadius: "999px",
                background: "var(--color-primary-faint)",
                color: "var(--color-primary)",
              }}
            >
              Best
            </span>
          )}
          {carFreeAnchor && !best && (
            <span
              style={{
                fontSize: "0.6875rem",
                fontWeight: 600,
                padding: "2px var(--space-2)",
                borderRadius: "999px",
                background: "var(--color-success-faint)",
                color: "var(--color-success)",
              }}
            >
              No car
            </span>
          )}
          {label && (
            <span
              style={{
                fontSize: "0.6875rem",
                padding: "2px var(--space-2)",
                borderRadius: "999px",
                background: driven ? "var(--color-warning-faint)" : "var(--color-surface-2)",
                color: driven ? "var(--color-warning)" : "var(--color-text-muted)",
                whiteSpace: "nowrap",
              }}
            >
              {label}
            </span>
          )}
        </div>
      </div>

      <div style={{ display: "flex", gap: "var(--space-5)" }}>
        <Stat value={`${option.changes}`} label={option.changes === 1 ? "change" : "changes"} />
        <Stat value={`${option.walk_min} min`} label="walking" />
        <Stat value={`${option.wait_min} min`} label="waiting" />
        {option.realtime && <Stat value="Live" label="times" />}
      </div>

      {option.legs?.length > 0 && (
        <>
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            style={{
              alignSelf: "flex-start",
              background: "none",
              border: "none",
              padding: 0,
              cursor: "pointer",
              fontSize: "0.75rem",
              color: "var(--color-primary)",
            }}
          >
            {open ? "Hide steps" : `Show ${option.legs.length} steps`}
          </button>
          {open && (
            <ul
              style={{
                listStyle: "none",
                margin: 0,
                padding: "var(--space-3) 0 0",
                borderTop: "1px solid var(--color-border)",
                display: "flex",
                flexDirection: "column",
                gap: "var(--space-2)",
              }}
            >
              {option.legs.map((leg, i) => (
                <LegRow key={i} leg={leg} />
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
