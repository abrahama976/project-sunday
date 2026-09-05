/**
 * The shapes the worker writes into travel_plans.
 *
 * Mirrors `_plain_summary` and `plan_as_row` in apps/worker/executors/travel_ops.py.
 * Datetimes arrive as ISO strings because Postgres will not take a Python
 * datetime through PostgREST, and the worker converts them explicitly.
 */

/** One leg of a journey: a walk, a drive, a bus, a train. */
export type Leg = {
  mode: string;          // Walk | Drive | Dropped off | Bus | Train | Metro | …
  line: string;          // "358", "T8", "" for a walk
  from: string;
  to: string;
  depart: string | null;
  arrive: string | null;
  minutes: number;
  realtime: boolean;
  km?: number | null;    // driving only
};

/**
 * `strategy` is the part that makes the fan-out visible. Without it there is
 * no way to tell whether the search actually ran several biased queries or
 * quietly fell back to the single baseline corridor it did for weeks.
 */
export type Option = {
  depart: string;
  arrive: string;
  duration_min: number;
  walk_min: number;
  wait_min: number;
  changes: number;
  realtime: boolean;
  strategy?: string;     // baseline | boarding | park_ride | drop_off | drive_direct
  headway_min?: number | null;
  drive_min?: number;
  fare?: number | null;
  legs: Leg[];
};

/** A journey the plausibility gate threw out, and why. */
export type Rejected = {
  reason: string;
  summary: Partial<Option>;
};

export type Plan = {
  id: string;
  origin_text: string | null;
  origin_label: string | null;
  destination_text: string | null;
  destination_label: string | null;
  arrive_by: string | null;
  depart_at: string | null;
  car_available: boolean;
  drop_off_available: boolean;
  options: Option[];
  rejected: Rejected[];
  drive: { minutes: number; km: number } | null;
  /** ok | ambiguous | implausible | not_found | failed */
  state: string;
  reason: string | null;
  created_at: string;
};

export type TravelRequest = {
  id: string;
  status: "pending" | "planning" | "done" | "failed";
  plan_id: string | null;
  error: string | null;
};

export type NearbyService = {
  id: string;
  stop_name: string;
  route: string;
  headsign: string | null;
  mode_class: number | null;
  headway_min: number | null;
  walk_min: number | null;
  source: string;
  is_hidden: boolean;
};

/** TfNSW product classes. 100 and 99 are walking legs. */
export const MODE_NAMES: Record<number, string> = {
  1: "Train",
  2: "Metro",
  4: "Light rail",
  5: "Bus",
  7: "Coach",
  9: "Ferry",
  11: "School bus",
};

/**
 * Why an option is in the list. Named for what actually happens rather than
 * for the code's own vocabulary — "park & ride" strands your car at the
 * station for the day and "dropped off" spends somebody else's half hour, and
 * a label that blurs the two is a label that misleads.
 */
export const STRATEGY_LABELS: Record<string, string> = {
  baseline: "Direct search",
  boarding: "From a nearby stop",
  park_ride: "Drive & park",
  drop_off: "Dropped off",
  drive_direct: "Drive all the way",
};

export const DRIVE_STRATEGIES = new Set(["park_ride", "drop_off", "drive_direct"]);

export function isDriven(option: Option): boolean {
  return DRIVE_STRATEGIES.has(option.strategy ?? "");
}

/** "7:23 PM" in the user's own timezone, from an ISO string. */
export function clock(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString("en-AU", {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
}

/** "48 min" or "1h 12m" — minutes stop being readable somewhere past an hour. */
export function duration(minutes: number | null | undefined): string {
  if (minutes == null) return "";
  const m = Math.round(minutes);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  const rest = m % 60;
  return rest ? `${h}h ${rest}m` : `${h}h`;
}
