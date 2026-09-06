"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";
import OptionCard from "./option_card";
import Services from "./services";
import { Plan, Option, isDriven, clock, duration, mapLink } from "./types";

/**
 * Travel — plan a trip, and see why each option is offered.
 *
 * Vercel cannot reach the worker on the Mac, so this does not call it. It
 * inserts a row into `travel_requests` and waits for the answer, exactly as
 * approvals and reminders already work. The worker polls every two seconds, so
 * an answer lands in roughly three to eight seconds depending on how many
 * searches the fan-out runs.
 *
 * Everything shown here comes from the structured plan the worker stores.
 * Before `travel_plans` existed the answer was rendered to a string the moment
 * it was computed, which is why this page could not have been built.
 */

const POLL_MS = 1500;
const GIVE_UP_MS = 90_000;

type When = "now" | "arrive" | "leave";
type Car = "none" | "driving" | "lift";

type CalEvent = {
  id: string;
  title: string;
  start_time: string;
  location: string | null;
};

/** The datetime-local value for "an hour from now", rounded to five minutes. */
function defaultWhen(): string {
  const d = new Date(Date.now() + 60 * 60 * 1000);
  d.setMinutes(Math.ceil(d.getMinutes() / 5) * 5, 0, 0);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export default function TravelPage() {
  const [userId, setUserId] = useState<string | null>(null);
  const [destination, setDestination] = useState("");
  const [origin, setOrigin] = useState("");
  const [useHere, setUseHere] = useState(false);
  const [when, setWhen] = useState<When>("now");
  const [at, setAt] = useState(defaultWhen);
  const [car, setCar] = useState<Car>("none");

  const [planning, setPlanning] = useState(false);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showRejected, setShowRejected] = useState(false);
  const [events, setEvents] = useState<CalEvent[]>([]);
  const [recent, setRecent] = useState<string[]>([]);

  // The poll is cleaned up on unmount and before each new plan, so leaving the
  // page mid-search cannot leave a timer writing into a dead component.
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      const supabase = createClient();
      const { data: { user } } = await supabase.auth.getUser();
      if (cancelled || !user) return;
      setUserId(user.id);

      const startOfDay = new Date();
      startOfDay.setHours(0, 0, 0, 0);
      const endOfDay = new Date(startOfDay);
      endOfDay.setDate(endOfDay.getDate() + 1);

      const [{ data: evs }, { data: plans }] = await Promise.all([
        supabase
          .from("calendar_events")
          .select("id, title, start_time, location")
          .eq("user_id", user.id)
          .gte("start_time", startOfDay.toISOString())
          .lt("start_time", endOfDay.toISOString())
          .order("start_time"),
        // Recent destinations, rather than a list you have to curate. The same
        // rows the learning job reads to work out where you actually go.
        supabase
          .from("travel_plans")
          .select("destination_label, destination_text, created_at")
          .eq("user_id", user.id)
          .eq("state", "ok")
          .order("created_at", { ascending: false })
          .limit(20),
      ]);

      if (cancelled) return;
      setEvents((evs ?? []) as CalEvent[]);
      // Deduplicated case-insensitively and capped at five: these are chips on
      // a 390px screen, and the same place typed two ways is one place.
      setRecent(
        (plans ?? [])
          .map((p) => (p.destination_label || p.destination_text || "").trim())
          .filter((n, i, arr) =>
            n && arr.findIndex((m) => m.toLowerCase() === n.toLowerCase()) === i)
          .slice(0, 5),
      );
    }

    void load();
    return () => { cancelled = true; };
  }, []);

  /**
   * Ask the phone where it is and tell the worker.
   *
   * `resolve_origin` has always preferred a live fix under fifteen minutes old
   * over the saved home address — but nothing in the app ever sent one, so
   * `user_location` was empty and that branch had never once run. The API
   * route existed the whole time with only a curl example for a caller.
   */
  const captureLocation = useCallback(async () => {
    if (!("geolocation" in navigator)) {
      setError("This browser will not share a location.");
      return false;
    }
    try {
      const pos = await new Promise<GeolocationPosition>((resolve, reject) =>
        navigator.geolocation.getCurrentPosition(resolve, reject, {
          enableHighAccuracy: true,
          timeout: 10_000,
          maximumAge: 60_000,
        }),
      );
      const res = await fetch("/api/location", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          lat: pos.coords.latitude,
          lng: pos.coords.longitude,
        }),
      });
      if (!res.ok) {
        setError("Could not save your location.");
        return false;
      }
      return true;
    } catch {
      setError("Location permission was declined, so I will start from home.");
      return false;
    }
  }, []);

  const startPlan = useCallback(
    async (dest: string, opts?: { car?: Car }) => {
      if (!userId || !dest.trim()) return;
      if (timer.current) clearTimeout(timer.current);
      setPlanning(true);
      setPlan(null);
      setError(null);
      setShowRejected(false);

      const mode = opts?.car ?? car;
      let originText: string | null = origin.trim() || null;
      if (useHere) {
        // A fresh fix makes resolve_origin prefer it; if the user declines, it
        // falls back to home, which is the behaviour they already had.
        await captureLocation();
        originText = null;
      }

      const supabase = createClient();
      const iso = when === "now" ? null : new Date(at).toISOString();
      const { data, error: err } = await supabase
        .from("travel_requests")
        .insert({
          user_id: userId,
          origin_text: originText,
          destination_text: dest.trim(),
          arrive_by: when === "arrive" ? iso : null,
          depart_at: when === "leave" ? iso : null,
          car_available: mode === "driving",
          drop_off_available: mode === "lift",
        })
        .select()
        .single();

      if (err || !data) {
        setPlanning(false);
        setError(err?.message ?? "Could not ask the worker to plan this.");
        return;
      }

      const startedAt = Date.now();
      const poll = async () => {
        const { data: req } = await supabase
          .from("travel_requests")
          .select("status, plan_id, error")
          .eq("id", data.id)
          .single();

        if (!req) return;

        if (req.status === "done" && req.plan_id) {
          const { data: p } = await supabase
            .from("travel_plans").select("*").eq("id", req.plan_id).single();
          setPlan((p ?? null) as Plan | null);
          setPlanning(false);
          return;
        }
        if (req.status === "failed") {
          // The plan row is still written on failure — it carries the state
          // and, when the place was ambiguous, the candidates to choose from.
          if (req.plan_id) {
            const { data: p } = await supabase
              .from("travel_plans").select("*").eq("id", req.plan_id).single();
            setPlan((p ?? null) as Plan | null);
          }
          setError(req.error ?? "Planning failed.");
          setPlanning(false);
          return;
        }
        if (Date.now() - startedAt > GIVE_UP_MS) {
          setPlanning(false);
          setError(
            "The worker did not answer. It may be offline — check Settings for its last heartbeat.",
          );
          return;
        }
        timer.current = setTimeout(() => void poll(), POLL_MS);
      };
      timer.current = setTimeout(() => void poll(), POLL_MS);
    },
    [userId, origin, useHere, when, at, car, captureLocation],
  );

  const options: Option[] = plan?.options ?? [];
  const carFreeIndex = options.findIndex((o) => !isDriven(o));
  const destinationMap = mapLink(plan?.destination_lat, plan?.destination_lng);

  return (
    <div style={{ maxWidth: "800px", margin: "0 auto", padding: "var(--space-6) var(--space-4) var(--space-12)" }}>
      <h1 style={{ fontSize: "1.125rem", fontWeight: 600, marginBottom: "var(--space-5)" }}>
        Travel
      </h1>

      {events.length > 0 && (
        <section style={{ marginBottom: "var(--space-6)" }}>
          <h2 style={{ fontSize: "0.9375rem", fontWeight: 600, margin: "0 0 var(--space-3)" }}>
            Today
          </h2>
          <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
            {events.map((ev) => (
              <div
                key={ev.id}
                style={{
                  display: "flex", alignItems: "center", gap: "var(--space-3)",
                  background: "var(--color-surface)",
                  border: "1px solid var(--color-border)",
                  borderRadius: "var(--radius-lg)",
                  padding: "var(--space-3) var(--space-4)",
                }}
              >
                <span
                  style={{
                    flexShrink: 0, fontFamily: "var(--font-mono)", fontSize: "0.75rem",
                    color: "var(--color-text-muted)", fontVariantNumeric: "tabular-nums",
                  }}
                >
                  {clock(ev.start_time)}
                </span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: "0.875rem", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {ev.title}
                  </div>
                  {ev.location && (
                    <div style={{ fontSize: "0.6875rem", color: "var(--color-text-faint)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {ev.location}
                    </div>
                  )}
                </div>
                {ev.location && (
                  <button
                    type="button"
                    onClick={() => {
                      setDestination(ev.location!);
                      setWhen("arrive");
                      setAt(toLocalInput(ev.start_time));
                      void startPlan(ev.location!);
                    }}
                    style={chipButton}
                  >
                    Plan
                  </button>
                )}
              </div>
            ))}
          </div>
          <Link
            href="/schedule"
            style={{ display: "inline-block", marginTop: "var(--space-2)", fontSize: "0.75rem", color: "var(--color-primary)" }}
          >
            Full week →
          </Link>
        </section>
      )}

      {/* ── The planner ─────────────────────────────────────── */}
      <section
        style={{
          background: "var(--color-surface)",
          border: "1px solid var(--color-border)",
          borderRadius: "var(--radius-lg)",
          padding: "var(--space-4)",
          display: "flex", flexDirection: "column", gap: "var(--space-3)",
          marginBottom: "var(--space-6)",
        }}
      >
        <input
          value={destination}
          onChange={(e) => setDestination(e.target.value)}
          placeholder="Where to?"
          onKeyDown={(e) => { if (e.key === "Enter") void startPlan(destination); }}
          style={{ ...inputStyle, fontSize: "1rem" }}
        />

        {recent.length > 0 && (
          <div style={{ display: "flex", gap: "var(--space-2)", flexWrap: "wrap" }}>
            {recent.map((r) => (
              <button
                key={r}
                type="button"
                onClick={() => { setDestination(r); void startPlan(r); }}
                style={chipButton}
              >
                {r}
              </button>
            ))}
          </div>
        )}

        <div style={{ display: "flex", gap: "var(--space-2)", alignItems: "center", flexWrap: "wrap" }}>
          <Segmented
            options={[["now", "Leave now"], ["arrive", "Arrive by"], ["leave", "Leave at"]]}
            value={when}
            onChange={(v) => setWhen(v as When)}
          />
          {when !== "now" && (
            <input
              type="datetime-local"
              value={at}
              onChange={(e) => setAt(e.target.value)}
              style={{ ...inputStyle, flex: "1 1 12rem" }}
            />
          )}
        </div>

        <div>
          <div style={{ fontSize: "0.6875rem", color: "var(--color-text-faint)", marginBottom: "var(--space-1)" }}>
            Getting there
          </div>
          <Segmented
            options={[["none", "Transit only"], ["driving", "I have the car"], ["lift", "Someone can drop me"]]}
            value={car}
            onChange={(v) => setCar(v as Car)}
          />
          {/* Stated, because the difference is physical: with a lift there is
              no car to leave at a station, so parking is never offered. */}
          <p style={{ fontSize: "0.6875rem", color: "var(--color-text-faint)", margin: "var(--space-2) 0 0" }}>
            {car === "none" && "No driving options — public transport and walking only."}
            {car === "driving" && "Adds driving to a station and parking, and driving the whole way."}
            {car === "lift" && "Adds being dropped at any stop. No parking, since the car goes home."}
          </p>
        </div>

        <label style={{ display: "flex", alignItems: "center", gap: "var(--space-2)", fontSize: "0.8125rem", color: "var(--color-text-muted)" }}>
          <input type="checkbox" checked={useHere} onChange={(e) => setUseHere(e.target.checked)} />
          Start from where I am now
        </label>

        {!useHere && (
          <input
            value={origin}
            onChange={(e) => setOrigin(e.target.value)}
            placeholder="From (blank = home)"
            style={inputStyle}
          />
        )}

        <button
          type="button"
          disabled={planning || !destination.trim()}
          onClick={() => void startPlan(destination)}
          style={{
            padding: "var(--space-3)",
            borderRadius: "var(--radius-md)",
            border: "none",
            background: planning || !destination.trim() ? "var(--color-surface-2)" : "var(--color-primary)",
            color: planning || !destination.trim() ? "var(--color-text-faint)" : "var(--color-bg)",
            fontSize: "0.9375rem",
            fontWeight: 600,
            cursor: planning || !destination.trim() ? "default" : "pointer",
          }}
        >
          {planning ? "Planning…" : "Plan"}
        </button>
      </section>

      {error && (
        <p style={{ fontSize: "0.8125rem", color: "var(--color-danger)", marginBottom: "var(--space-4)" }}>
          {error}
        </p>
      )}

      {plan && plan.state !== "ok" && (
        <div
          style={{
            background: "var(--color-warning-faint)",
            border: "1px solid var(--color-warning)",
            borderRadius: "var(--radius-lg)",
            padding: "var(--space-4)",
            marginBottom: "var(--space-4)",
          }}
        >
          <p style={{ margin: 0, fontSize: "0.875rem" }}>{plan.reason}</p>

          {/* The candidates, as a choice rather than a sentence. Tapping one
              re-plans against that exact name; the pin beside it is how you
              tell two identically-named suburbs apart before you commit. */}
          {(plan.place_options?.length ?? 0) > 0 && (
            <div style={{ marginTop: "var(--space-3)" }}>
              <div style={{ fontSize: "0.75rem", color: "var(--color-text-muted)", marginBottom: "var(--space-2)" }}>
                Did you mean {plan.unresolved === "origin" ? "one of these to start from" : "one of these"}?
              </div>
              <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
                {plan.place_options!.map((option, i) => (
                  <li key={i} style={{ display: "flex", alignItems: "center", gap: "var(--space-2)" }}>
                    <button
                      type="button"
                      onClick={() => {
                        setDestination(option.name);
                        void startPlan(option.name);
                      }}
                      style={{
                        flex: 1,
                        textAlign: "left",
                        minWidth: 0,
                        padding: "var(--space-2) var(--space-3)",
                        borderRadius: "var(--radius-md)",
                        border: "1px solid var(--color-border)",
                        background: "var(--color-surface)",
                        color: "var(--color-text)",
                        fontSize: "0.8125rem",
                        fontFamily: "inherit",
                        cursor: "pointer",
                      }}
                    >
                      {option.name}
                      {option.kind && (
                        <span style={{ color: "var(--color-text-faint)" }}> · {option.kind}</span>
                      )}
                    </button>
                    {option.map_url && (
                      <a
                        href={option.map_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{ flexShrink: 0, fontSize: "0.75rem", color: "var(--color-primary)" }}
                      >
                        Map
                      </a>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* A failure that still resolved a coordinate is the most useful
              place of all to offer the pin: "every option was implausible" and
              "it resolved 400 km away" read identically until you look. */}
          {destinationMap && (
            <p style={{ margin: "var(--space-2) 0 0", fontSize: "0.75rem" }}>
              It searched to{" "}
              <a
                href={destinationMap}
                target="_blank"
                rel="noopener noreferrer"
                style={{ color: "var(--color-primary)" }}
              >
                this point
              </a>
              . If that is the wrong place, name the suburb too.
            </p>
          )}
        </div>
      )}

      {plan && options.length > 0 && (
        <section style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)", marginBottom: "var(--space-6)" }}>
          <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: "var(--space-3)" }}>
            <h2 style={{ fontSize: "0.9375rem", fontWeight: 600, margin: 0, minWidth: 0 }}>
              {plan.destination_label || plan.destination_text}
            </h2>
            <span style={{ fontSize: "0.6875rem", color: "var(--color-text-faint)", flexShrink: 0 }}>
              from {plan.origin_label || "home"}
              {/* One tap to see where Sunday thinks it is going. Everything
                  below this line is correct *about that coordinate*, so when
                  the answer feels wrong this is the first thing to check. */}
              {destinationMap && (
                <>
                  {" · "}
                  <a
                    href={destinationMap}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ color: "var(--color-primary)" }}
                  >
                    Map
                  </a>
                </>
              )}
            </span>
          </div>

          {options.map((o, i) => (
            <OptionCard key={i} option={o} best={i === 0} carFreeAnchor={i === carFreeIndex} />
          ))}

          {plan.drive && (
            <p style={{ fontSize: "0.75rem", color: "var(--color-text-muted)", margin: 0 }}>
              Driving door to door: {duration(plan.drive.minutes)}
              {plan.drive.km ? ` (${plan.drive.km.toFixed(1)} km)` : ""}.
            </p>
          )}

          {plan.rejected?.length > 0 && (
            <>
              <button
                type="button"
                onClick={() => setShowRejected((v) => !v)}
                style={{
                  alignSelf: "flex-start", background: "none", border: "none", padding: 0,
                  cursor: "pointer", fontSize: "0.75rem", color: "var(--color-text-muted)",
                }}
              >
                {showRejected ? "Hide" : `${plan.rejected.length} ruled out`}
              </button>
              {showRejected && (
                <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
                  {plan.rejected.map((r, i) => (
                    <li key={i} style={{ fontSize: "0.75rem", color: "var(--color-text-faint)" }}>
                      {r.summary?.depart ? `${clock(r.summary.depart)} — ` : ""}
                      {r.reason}
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
        </section>
      )}

      <Services userId={userId} />
    </div>
  );
}

/* ── Small pieces ──────────────────────────────────────────── */

function Segmented({
  options, value, onChange,
}: {
  options: [string, string][];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div
      role="radiogroup"
      style={{
        display: "inline-flex", gap: "2px", padding: "2px",
        background: "var(--color-surface-2)",
        borderRadius: "var(--radius-md)",
        flexWrap: "wrap",
      }}
    >
      {options.map(([v, label]) => (
        <button
          key={v}
          type="button"
          role="radio"
          aria-checked={value === v}
          onClick={() => onChange(v)}
          style={{
            padding: "var(--space-2) var(--space-3)",
            borderRadius: "var(--radius-sm)",
            border: "none",
            cursor: "pointer",
            fontSize: "0.75rem",
            fontWeight: value === v ? 600 : 400,
            background: value === v ? "var(--color-primary)" : "transparent",
            color: value === v ? "var(--color-bg)" : "var(--color-text-muted)",
          }}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

/** An ISO instant as the local value a datetime-local input expects. */
function toLocalInput(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

const inputStyle: React.CSSProperties = {
  padding: "var(--space-3)",
  borderRadius: "var(--radius-md)",
  border: "1px solid var(--color-border)",
  background: "var(--color-bg)",
  color: "var(--color-text)",
  fontSize: "0.875rem",
  fontFamily: "inherit",
  width: "100%",
};

const chipButton: React.CSSProperties = {
  padding: "var(--space-1) var(--space-3)",
  borderRadius: "999px",
  border: "1px solid var(--color-border)",
  background: "var(--color-surface-2)",
  color: "var(--color-text-muted)",
  fontSize: "0.75rem",
  cursor: "pointer",
  whiteSpace: "nowrap",
};
