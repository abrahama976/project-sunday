"use client";

import { useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { NearbyService, MODE_NAMES, mapLink, MAX_WALK_MIN } from "./types";

/**
 * The local network, and the ability to correct it.
 *
 * `nearby_services` was designed to be correctable from the start — `is_hidden`
 * retires a route without deleting what discovery found, and `source='user'`
 * marks a row the weekly refresh must never overwrite, because the API not
 * knowing about a service you catch daily should not mean Sunday forgets it
 * every Sunday night. The columns shipped in #35; the controls did not, so the
 * design has been half-built ever since.
 *
 * With 93 services across 35 stops, curation stopped being optional.
 */

function modeName(cls: number | null): string {
  return cls == null ? "" : MODE_NAMES[cls] ?? "";
}

function ServiceRow({
  service,
  onToggle,
}: {
  service: NearbyService;
  onToggle: (s: NearbyService) => void;
}) {
  const rail = service.mode_class === 1 || service.mode_class === 2;
  return (
    <li
      className="row gap-3"
      style={{ padding: "var(--space-2) 0", opacity: service.is_hidden ? 0.45 : 1 }}
    >
      {/* The route number is the thing you scan for, so it gets a fixed width
          and tabular digits — 358 and 306 line up rather than jittering. */}
      <span
        className={`chip nums${rail ? " chip-primary" : ""}`}
        style={{
          flexShrink: 0,
          minWidth: "2.75rem",
          textAlign: "center",
          borderRadius: "var(--radius-sm)",
          fontSize: "var(--text-xs)",
        }}
      >
        {service.route}
      </span>

      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          className="t-sm"
          style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
        >
          {service.headsign || modeName(service.mode_class) || "—"}
        </div>
        <div className="label">
          {service.walk_min != null ? `${service.walk_min} min walk` : "walk unknown"}
          {/* A frequency is only shown when it was measured. A guessed one gets
              read as fact and changes when somebody leaves the house. */}
          {service.headway_min != null ? ` · every ~${service.headway_min} min` : ""}
          {service.source === "user" ? " · yours" : ""}
        </div>
      </div>

      <button
        type="button"
        onClick={() => onToggle(service)}
        className="btn t-2xs"
        style={{
          flexShrink: 0,
          background: "none",
          borderRadius: "var(--radius-sm)",
          padding: "2px var(--space-2)",
          color: "var(--color-text-muted)",
        }}
      >
        {service.is_hidden ? "Restore" : "Hide"}
      </button>
    </li>
  );
}

export default function Services({ userId }: { userId: string | null }) {
  const [services, setServices] = useState<NearbyService[] | null>(null);
  const [showHidden, setShowHidden] = useState(false);
  const [showFar, setShowFar] = useState(false);
  const [adding, setAdding] = useState(false);
  const [route, setRoute] = useState("");
  const [stop, setStop] = useState("");
  const [headsign, setHeadsign] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    // Defined inside the effect: react-hooks/set-state-in-effect flags a
    // setState-containing function declared outside one, even an async one.
    async function load() {
      if (!userId) return;
      const supabase = createClient();
      const { data, error: err } = await supabase
        .from("nearby_services")
        .select("id, stop_name, stop_lat, stop_lng, route, headsign, mode_class, headway_min, walk_min, source, is_hidden")
        .eq("user_id", userId)
        .order("walk_min", { ascending: true })
        .order("route", { ascending: true });
      if (cancelled) return;
      if (err) {
        setError(err.message);
        setServices([]);
        return;
      }
      setServices((data ?? []) as NearbyService[]);
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [userId]);

  async function toggle(service: NearbyService) {
    // Optimistic: the row is already on screen and the write is a single
    // boolean. Reverted below if it fails, so the list never claims a change
    // the database did not take.
    const next = !service.is_hidden;
    setServices((current) =>
      (current ?? []).map((s) => (s.id === service.id ? { ...s, is_hidden: next } : s)),
    );
    const supabase = createClient();
    const { error: err } = await supabase
      .from("nearby_services")
      .update({ is_hidden: next })
      .eq("id", service.id);
    if (err) {
      setError(err.message);
      setServices((current) =>
        (current ?? []).map((s) =>
          s.id === service.id ? { ...s, is_hidden: service.is_hidden } : s,
        ),
      );
    }
  }

  async function add(e: React.FormEvent) {
    e.preventDefault();
    if (!userId || !route.trim() || !stop.trim()) return;
    const supabase = createClient();
    // source='user' is the point: discovery only ever writes 'discovered', so
    // a row added here survives the weekly refresh.
    const { data, error: err } = await supabase
      .from("nearby_services")
      .insert({
        user_id: userId,
        stop_name: stop.trim(),
        route: route.trim(),
        headsign: headsign.trim(),
        source: "user",
      })
      .select()
      .single();
    if (err) {
      setError(err.message);
      return;
    }
    setServices((current) => [...(current ?? []), data as NearbyService]);
    setRoute("");
    setStop("");
    setHeadsign("");
    setAdding(false);
    setError(null);
  }

  if (!services) {
    return (
      <p className="t-sm faint">Loading services…</p>
    );
  }

  const visible = services.filter((s) => !s.is_hidden);
  const hidden = services.filter((s) => s.is_hidden);
  const shown = showHidden ? services : visible;

  // Past your stated 20-minute limit it is not really a walk, and with 93
  // services the far ones bury the ones at the corner. Collapsed rather than
  // hidden in the database: an automatic decision that rewrites `is_hidden`
  // would fight you every week when discovery re-runs, and would silently
  // undo an un-hide. This is presentation only — nothing is written.
  const near = shown.filter((s) => (s.walk_min ?? 0) <= MAX_WALK_MIN);
  const far = shown.filter((s) => (s.walk_min ?? 0) > MAX_WALK_MIN);
  const listed = showFar ? [...near, ...far] : near;

  const byStop = new Map<string, NearbyService[]>();
  for (const s of listed) {
    const list = byStop.get(s.stop_name) ?? [];
    list.push(s);
    byStop.set(s.stop_name, list);
  }

  return (
    <section className="col gap-3">
      <div className="row gap-3" style={{ alignItems: "baseline", justifyContent: "space-between" }}>
        <h2 className="t-md" style={{ fontWeight: 600 }}>
          Services near home
        </h2>
        <span className="t-xs faint">
          {near.length} within {MAX_WALK_MIN} min
        </span>
      </div>

      <p className="t-xs muted">
        What Sunday searches when planning. Hide what you would never catch — it
        narrows every search from here on. Anything you add is kept through the
        weekly refresh.
      </p>

      {error && (
        <p className="t-xs" style={{ color: "var(--color-danger)" }}>{error}</p>
      )}

      {byStop.size === 0 ? (
        <p className="t-sm faint">
          Nothing discovered yet. The worker fills this on startup and again
          every Sunday at 4am.
        </p>
      ) : (
        [...byStop.entries()].map(([stopName, list]) => (
          <div
            key={stopName}
            className="card card-tight"
          >
            <div
              style={{
                display: "flex",
                alignItems: "baseline",
                gap: "var(--space-2)",
                fontSize: "0.75rem",
                color: "var(--color-text-muted)",
                marginBottom: "var(--space-1)",
              }}
            >
              <span style={{ flex: 1, minWidth: 0 }}>{stopName}</span>
              {/* The coordinate, not the name. A stop can be named plausibly
                  and still be in the wrong suburb; only the pin says so. */}
              {(() => {
                const href = mapLink(list[0]?.stop_lat, list[0]?.stop_lng);
                return href ? (
                  <a
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ flexShrink: 0, color: "var(--color-primary)" }}
                  >
                    Map
                  </a>
                ) : null;
              })()}
            </div>
            <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
              {list.map((s) => (
                <ServiceRow key={s.id} service={s} onToggle={toggle} />
              ))}
            </ul>
          </div>
        ))
      )}

      <div className="row gap-3" style={{ flexWrap: "wrap" }}>
        {far.length > 0 && (
          <button
            type="button"
            onClick={() => setShowFar((v) => !v)}
            className="link-btn"
          >
            {showFar
              ? `Hide the ${far.length} further away`
              : `Show ${far.length} further than ${MAX_WALK_MIN} min`}
          </button>
        )}
        {hidden.length > 0 && (
          <button
            type="button"
            onClick={() => setShowHidden((v) => !v)}
            className="link-btn"
          >
            {showHidden ? "Hide retired" : `Show ${hidden.length} retired`}
          </button>
        )}
        <button
          type="button"
          onClick={() => setAdding((v) => !v)}
          className="link-btn"
        >
          {adding ? "Cancel" : "Add a service Sunday missed"}
        </button>
      </div>

      {adding && (
        <form
          onSubmit={add}
          className="card col gap-2"
          style={{ background: "var(--color-surface-2)" }}
        >
          <input
            value={route} onChange={(e) => setRoute(e.target.value)}
            placeholder="Route, e.g. 306" required
            className="field"
          />
          <input
            value={stop} onChange={(e) => setStop(e.target.value)}
            placeholder="Stop, e.g. Gardeners Rd at Rosebery" required
            className="field"
          />
          <input
            value={headsign} onChange={(e) => setHeadsign(e.target.value)}
            placeholder="Heading towards (optional)"
            className="field"
          />
          <button
            type="submit"
            className="btn btn-primary"
          >
            Add
          </button>
        </form>
      )}
    </section>
  );
}

