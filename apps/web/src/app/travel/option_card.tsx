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
 *
 * Styling comes from globals.css. This file used to carry 23 inline style
 * objects, several of which were the same card and the same chip written out
 * again with slightly different padding.
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
    <li className="row gap-3" style={{ alignItems: "baseline" }}>
      <span
        className="t-xs faint nums"
        style={{ flexShrink: 0, width: "3.25rem", fontFamily: "var(--font-mono)" }}
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
      <span className="t-sm" style={{ minWidth: 0 }}>
        {leg.line ? (
          <strong style={{ color: legTone(leg) }}>
            {leg.mode} {leg.line}
          </strong>
        ) : (
          <span className="muted">{leg.mode}</span>
        )}
        <span className="muted">
          {" "}
          {leg.minutes} min{leg.to ? ` → ${leg.to}` : ""}
        </span>
      </span>
    </li>
  );
}

function Stat({ value, label }: { value: string; label: string }) {
  return (
    <div className="col" style={{ gap: "1px" }}>
      <span className="t-sm nums">{value}</span>
      <span className="label">{label}</span>
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
    <div className={`card col gap-3${best ? " card-accent" : ""}`}>
      <div className="row gap-3" style={{ alignItems: "flex-start" }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="label">Leave</div>
          <div
            className="t-lg nums"
            style={{ fontWeight: 600, lineHeight: 1.1 }}
          >
            {clock(option.depart)}
          </div>
          <div className="t-sm muted" style={{ marginTop: "2px" }}>
            arrive {clock(option.arrive)} · {duration(option.duration_min)}
          </div>
        </div>

        <div className="col gap-1" style={{ alignItems: "flex-end" }}>
          {best && <span className="chip chip-primary">Best</span>}
          {carFreeAnchor && !best && (
            <span className="chip chip-success">No car</span>
          )}
          {label && (
            <span className={`chip${driven ? " chip-warning" : ""}`}>
              {label}
            </span>
          )}
        </div>
      </div>

      <div className="row" style={{ gap: "var(--space-5)" }}>
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
            className="link-btn"
            style={{ alignSelf: "flex-start" }}
          >
            {open ? "Hide steps" : `Show ${option.legs.length} steps`}
          </button>
          {open && (
            <ul
              className="col gap-2"
              style={{
                listStyle: "none",
                padding: "var(--space-3) 0 0",
                borderTop: "1px solid var(--color-border)",
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
