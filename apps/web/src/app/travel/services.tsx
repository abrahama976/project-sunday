"use client";

import { useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { NearbyService, MODE_NAMES, mapLink } from "./types";

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
      style={{
        display: "flex",
        alignItems: "center",
        gap: "var(--space-3)",
        padding: "var(--space-2) 0",
        opacity: service.is_hidden ? 0.45 : 1,
      }}
    >
      <span
        style={{
          flexShrink: 0,
          minWidth: "2.75rem",
          textAlign: "center",
          padding: "2px var(--space-2)",
          borderRadius: "var(--radius-sm)",
          background: rail ? "var(--color-primary-faint)" : "var(--color-surface-2)",
          color: rail ? "var(--color-primary)" : "var(--color-text)",
          fontSize: "0.75rem",
          fontWeight: 600,
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {service.route}
      </span>

      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            fontSize: "0.8125rem",
            color: "var(--color-text)",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {service.headsign || modeName(service.mode_class) || "—"}
        </div>
        <div style={{ fontSize: "0.6875rem", color: "var(--color-text-faint)" }}>
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
        style={{
          flexShrink: 0,
          background: "none",
          border: "1px solid var(--color-border)",
          borderRadius: "var(--radius-sm)",
          padding: "2px var(--space-2)",
          fontSize: "0.6875rem",
          color: "var(--color-text-muted)",
          cursor: "pointer",
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
      <p style={{ fontSize: "0.8125rem", color: "var(--color-text-faint)" }}>
        Loading services…
      </p>
    );
  }

  const visible = services.filter((s) => !s.is_hidden);
  const hidden = services.filter((s) => s.is_hidden);
  const shown = showHidden ? services : visible;

  const byStop = new Map<string, NearbyService[]>();
  for (const s of shown) {
    const list = byStop.get(s.stop_name) ?? [];
    list.push(s);
    byStop.set(s.stop_name, list);
  }

  return (
    <section style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: "var(--space-3)" }}>
        <h2 style={{ fontSize: "0.9375rem", fontWeight: 600, margin: 0 }}>
          Services near home
        </h2>
        <span style={{ fontSize: "0.75rem", color: "var(--color-text-faint)" }}>
          {visible.length} in use
        </span>
      </div>

      <p style={{ fontSize: "0.75rem", color: "var(--color-text-muted)", margin: 0 }}>
        What Sunday searches when planning. Hide what you would never catch — it
        narrows every search from here on. Anything you add is kept through the
        weekly refresh.
      </p>

      {error && (
        <p style={{ fontSize: "0.75rem", color: "var(--color-danger)", margin: 0 }}>
          {error}
        </p>
      )}

      {byStop.size === 0 ? (
        <p style={{ fontSize: "0.8125rem", color: "var(--color-text-faint)" }}>
          Nothing discovered yet. The worker fills this on startup and again
          every Sunday at 4am.
        </p>
      ) : (
        [...byStop.entries()].map(([stopName, list]) => (
          <div
            key={stopName}
            style={{
              background: "var(--color-surface)",
              border: "1px solid var(--color-border)",
              borderRadius: "var(--radius-lg)",
              padding: "var(--space-3) var(--space-4)",
            }}
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

      <div style={{ display: "flex", gap: "var(--space-3)", flexWrap: "wrap" }}>
        {hidden.length > 0 && (
          <button
            type="button"
            onClick={() => setShowHidden((v) => !v)}
            style={{
              background: "none", border: "none", padding: 0, cursor: "pointer",
              fontSize: "0.75rem", color: "var(--color-primary)",
            }}
          >
            {showHidden ? "Hide retired" : `Show ${hidden.length} retired`}
          </button>
        )}
        <button
          type="button"
          onClick={() => setAdding((v) => !v)}
          style={{
            background: "none", border: "none", padding: 0, cursor: "pointer",
            fontSize: "0.75rem", color: "var(--color-primary)",
          }}
        >
          {adding ? "Cancel" : "Add a service Sunday missed"}
        </button>
      </div>

      {adding && (
        <form
          onSubmit={add}
          style={{
            display: "flex", flexDirection: "column", gap: "var(--space-2)",
            background: "var(--color-surface-2)",
            border: "1px solid var(--color-border)",
            borderRadius: "var(--radius-lg)",
            padding: "var(--space-4)",
          }}
        >
          <input
            value={route} onChange={(e) => setRoute(e.target.value)}
            placeholder="Route, e.g. 306" required
            style={inputStyle}
          />
          <input
            value={stop} onChange={(e) => setStop(e.target.value)}
            placeholder="Stop, e.g. Gardeners Rd at Rosebery" required
            style={inputStyle}
          />
          <input
            value={headsign} onChange={(e) => setHeadsign(e.target.value)}
            placeholder="Heading towards (optional)"
            style={inputStyle}
          />
          <button
            type="submit"
            style={{
              padding: "var(--space-2) var(--space-4)",
              borderRadius: "var(--radius-md)",
              border: "none",
              background: "var(--color-primary)",
              color: "var(--color-bg)",
              fontSize: "0.8125rem",
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Add
          </button>
        </form>
      )}
    </section>
  );
}

const inputStyle: React.CSSProperties = {
  padding: "var(--space-2) var(--space-3)",
  borderRadius: "var(--radius-md)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg)",
  color: "var(--color-text)",
  fontSize: "0.875rem",
  fontFamily: "inherit",
};
