"use client";

/**
 * Saved places — the fixed locations Sunday routes from.
 *
 * Without one of these marked default, `travel_directions` has no origin to
 * fall back on when the phone has not reported a recent position, so the model
 * stops and asks "where will you be coming from?" every time.
 *
 * Addresses are stored as text and geocoded by Google when a route is planned;
 * lat/lng stay null unless something else fills them in. One less API key in
 * the browser, and a typo shows up as a wrong route rather than a silent null.
 */

import { useEffect, useMemo, useState } from "react";
import { createClient } from "@/lib/supabase/client";

type Place = {
  id: string;
  label: string;
  address: string;
  is_default: boolean;
};

function isPlace(x: unknown): x is Place {
  if (!x || typeof x !== "object") return false;
  const o = x as Record<string, unknown>;
  return (
    typeof o.id === "string" &&
    typeof o.label === "string" &&
    typeof o.address === "string" &&
    typeof o.is_default === "boolean"
  );
}

const inputStyle = {
  width: "100%",
  padding: "var(--space-3)",
  background: "var(--color-surface-2)",
  border: "1px solid var(--color-border)",
  borderRadius: "var(--radius-md)",
  color: "var(--color-text)",
  fontSize: "0.9375rem",
  outline: "none",
} as const;

export default function SavedPlaces() {
  const supabase = useMemo(() => createClient(), []);
  const [places, setPlaces] = useState<Place[]>([]);
  const [label, setLabel] = useState("");
  const [address, setAddress] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  // Loader inside the effect: lifting it to a useCallback trips
  // react-hooks/set-state-in-effect, which cannot see past a call boundary.
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      const { data, error: err } = await supabase
        .from("saved_places")
        .select("id, label, address, is_default")
        .order("is_default", { ascending: false })
        .order("label", { ascending: true });
      if (cancelled) return;
      if (err) {
        setError(err.message);
        return;
      }
      setPlaces((data ?? []).filter(isPlace));
    };
    void load().catch((e: unknown) => {
      if (cancelled) return;
      setError(e instanceof Error ? e.message : "Could not load places.");
    });
    return () => {
      cancelled = true;
    };
  }, [supabase, reloadKey]);

  const refresh = () => setReloadKey((k) => k + 1);

  const add = async () => {
    if (!label.trim() || !address.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) throw new Error("Not signed in");
      const { error: err } = await supabase.from("saved_places").insert({
        user_id: user.id,
        label: label.trim(),
        address: address.trim(),
        // First place added becomes the default, so a single entry is enough
        // to make routing work without a second deliberate step.
        is_default: places.length === 0,
      });
      if (err) throw err;
      setLabel("");
      setAddress("");
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save that place.");
    } finally {
      setBusy(false);
    }
  };

  const makeDefault = async (id: string) => {
    setBusy(true);
    setError(null);
    try {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) throw new Error("Not signed in");
      // Clear first: the schema has a partial unique index allowing one default
      // per user, so setting a second before clearing the first is rejected.
      await supabase
        .from("saved_places")
        .update({ is_default: false })
        .eq("user_id", user.id)
        .eq("is_default", true);
      const { error: err } = await supabase
        .from("saved_places")
        .update({ is_default: true })
        .eq("id", id);
      if (err) throw err;
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not change the default.");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (id: string) => {
    setBusy(true);
    setError(null);
    try {
      const { error: err } = await supabase.from("saved_places").delete().eq("id", id);
      if (err) throw err;
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not delete that place.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section>
      <h2 style={{ fontSize: "0.8125rem", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--color-text-faint)", marginBottom: "var(--space-3)" }}>
        Places
      </h2>

      <div style={{
        background: "var(--color-surface)",
        border: "1px solid var(--color-border)",
        borderRadius: "var(--radius-lg)",
        padding: "var(--space-4) var(--space-5)",
        display: "flex",
        flexDirection: "column",
        gap: "var(--space-4)",
      }}>
        <p style={{ fontSize: "0.8125rem", color: "var(--color-text-muted)", margin: 0, lineHeight: 1.5 }}>
          Where Sunday starts a journey from when you don&apos;t say. Your live
          position is used instead while it&apos;s recent; otherwise it falls
          back to the default below.
        </p>

        {places.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
            {places.map((p) => (
              <div
                key={p.id}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "var(--space-3)",
                  padding: "var(--space-3)",
                  background: "var(--color-surface-2)",
                  border: "1px solid var(--color-border)",
                  borderRadius: "var(--radius-md)",
                }}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)" }}>
                    <span style={{ fontSize: "0.9375rem", fontWeight: 500, textTransform: "capitalize" }}>
                      {p.label}
                    </span>
                    {p.is_default && (
                      <span style={{
                        fontSize: "0.625rem",
                        textTransform: "uppercase",
                        letterSpacing: "0.04em",
                        padding: "2px 6px",
                        borderRadius: "var(--radius-sm)",
                        background: "var(--color-primary-faint)",
                        color: "var(--color-primary)",
                        fontWeight: 600,
                      }}>
                        Default
                      </span>
                    )}
                  </div>
                  <div style={{
                    fontSize: "0.8125rem",
                    color: "var(--color-text-muted)",
                    marginTop: 2,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}>
                    {p.address}
                  </div>
                </div>

                {!p.is_default && (
                  <button
                    onClick={() => void makeDefault(p.id)}
                    disabled={busy}
                    style={{
                      background: "transparent",
                      border: "none",
                      color: "var(--color-primary)",
                      fontSize: "0.75rem",
                      cursor: busy ? "not-allowed" : "pointer",
                      flexShrink: 0,
                      padding: "var(--space-1)",
                    }}
                  >
                    Make default
                  </button>
                )}
                <button
                  onClick={() => void remove(p.id)}
                  disabled={busy}
                  aria-label={`Delete ${p.label}`}
                  style={{
                    background: "transparent",
                    border: "none",
                    color: "var(--color-text-faint)",
                    cursor: busy ? "not-allowed" : "pointer",
                    flexShrink: 0,
                    padding: "var(--space-1)",
                  }}
                >
                  ✕
                </button>
              </div>
            ))}
          </div>
        )}

        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="Label — home, work, gym"
            style={inputStyle}
          />
          <input
            value={address}
            onChange={(e) => setAddress(e.target.value)}
            placeholder="Address — 1 Example St, Sydney NSW 2000"
            style={inputStyle}
          />
          <button
            onClick={() => void add()}
            disabled={busy || !label.trim() || !address.trim()}
            style={{
              alignSelf: "flex-start",
              padding: "var(--space-2) var(--space-4)",
              background: busy || !label.trim() || !address.trim()
                ? "var(--color-surface-2)" : "var(--color-primary)",
              border: "1px solid var(--color-border)",
              borderRadius: "var(--radius-md)",
              fontSize: "0.875rem",
              color: busy || !label.trim() || !address.trim()
                ? "var(--color-text-faint)" : "#fff",
              fontWeight: 500,
              cursor: busy || !label.trim() || !address.trim() ? "not-allowed" : "pointer",
            }}
          >
            {places.length === 0 ? "Add and use as default" : "Add place"}
          </button>
        </div>

        {error && (
          <div style={{ fontSize: "0.8125rem", color: "var(--color-danger)" }}>{error}</div>
        )}
      </div>
    </section>
  );
}
