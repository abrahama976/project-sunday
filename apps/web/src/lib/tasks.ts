/**
 * One definition of a task, shared by every screen that shows one.
 *
 * Three screens each carried their own `Task` type and `isTask` guard, and they
 * drifted apart. Today accepted priority 1–5; Tasks accepted 0–3 and therefore
 * silently dropped every high-priority row it was sent — the two things that
 * were late and due today were the two it hid. The database is unambiguous:
 * `tasks_priority_range CHECK (priority >= 1 AND priority <= 5)`. That ladder
 * is defined here, once, so the next screen cannot invent a fourth.
 *
 * The two screens also disagreed about what "late" meant, because each counted
 * with its own copy of the date logic. Counts and the views they open now go
 * through the same predicates: `isOverdue` / `isDueToday`, and `matchesFilter`
 * for the `/tasks?filter=…` views.
 */

export type TaskPriority = 1 | 2 | 3 | 4 | 5;

/**
 * The four values `tasks_status_check` permits.
 *
 * The guard accepts all four even though every screen currently asks for
 * `status = "open"`, because a guard that knew only `open | done` would drop an
 * in-progress or cancelled task on the floor — the same silent-loss bug as the
 * priority guard this module replaces, one column over. Screens pick their
 * subset in the query, where the exclusion is visible, not by narrowing a type.
 */
export type TaskStatus = "open" | "in_progress" | "done" | "cancelled";

export type Task = {
  id: string;
  title: string;
  status: TaskStatus;
  priority: TaskPriority;
  due_date: string | null;
  category: string | null;
  is_archived: boolean;
  created_at: string;
};

/**
 * A runtime guard for rows that came back from PostgREST as `unknown`.
 *
 * It validates shape, not policy: a row that passes is safe to render. Rows are
 * additionally filtered by query (`status = "open"`, `is_archived = false`) —
 * the guard is not the place to decide what belongs on a screen.
 */
export function isTask(x: unknown): x is Task {
  if (!x || typeof x !== "object") return false;
  const o = x as Record<string, unknown>;
  return (
    typeof o.id === "string" &&
    typeof o.title === "string" &&
    (o.status === "open" || o.status === "in_progress" ||
      o.status === "done" || o.status === "cancelled") &&
    (o.priority === 1 || o.priority === 2 || o.priority === 3 ||
      o.priority === 4 || o.priority === 5) &&
    (o.due_date === null || typeof o.due_date === "string") &&
    (o.category === null || typeof o.category === "string") &&
    typeof o.is_archived === "boolean" &&
    typeof o.created_at === "string"
  );
}

/* ── Priority ladder ──────────────────────────────────────────
   1 Low · 2 Normal · 3 Medium · 4 High · 5 Critical.

   This replaces a 0–3 ladder whose top rung was called "High" at 3, while
   Today called 4 and above "High". Colour climbs with importance using the
   existing tokens, so the meaning survives a palette change. */

export const PRIORITY_LABELS: Record<TaskPriority, string> = {
  1: "Low",
  2: "Normal",
  3: "Medium",
  4: "High",
  5: "Critical",
};

export const PRIORITY_COLORS: Record<TaskPriority, string> = {
  1: "var(--color-text-faint)",
  2: "var(--color-text-muted)",
  3: "var(--color-primary)",
  4: "var(--color-warning)",
  5: "var(--color-danger)",
};

/** Only the top two rungs earn a badge; 1–3 are already visible as text. */
export type PriorityBadge = { label: string; className: string };

const PRIORITY_BADGES: Record<TaskPriority, PriorityBadge | null> = {
  1: null,
  2: null,
  3: null,
  4: { label: "High", className: "chip chip-warning" },
  5: { label: "Critical", className: "chip chip-danger" },
};

/**
 * The badge rides with its chip class. Left to the screens, each one wrote its
 * own `priority === 5 ? "chip-danger" : "chip-warning"` and the two would drift
 * on the next palette change.
 */
export function priorityBadge(priority: TaskPriority): PriorityBadge | null {
  return PRIORITY_BADGES[priority];
}

/* ── Dates ────────────────────────────────────────────────────
   Every helper takes `now`. A date read from the clock during render is a
   hydration mismatch waiting to happen, and a value frozen at mount made this
   dashboard report a stale state indefinitely. */

export type Due = { label: string; tone: "danger" | "warning" | "muted" };

/** Midnight local, as a number — the day boundary a person actually uses. */
export function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

/**
 * `tasks.due_date` is a DATE column, so PostgREST returns "2026-11-15" with no
 * time, and `new Date("2026-11-15")` reads that as UTC midnight — which is the
 * previous calendar day anywhere west of UTC, so a task due today would report
 * "1 day late" in Los Angeles. Build local midnight from the parts instead.
 * A full timestamp still parses normally.
 */
function parseDueDate(due: string): Date | null {
  const dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(due);
  const at = dateOnly
    ? new Date(Number(dateOnly[1]), Number(dateOnly[2]) - 1, Number(dateOnly[3]))
    : new Date(due);
  return Number.isNaN(at.getTime()) ? null : at;
}

/**
 * Whole local days from today to the due date: negative is late, 0 is today.
 * Null when there is no due date, or when it does not parse — the single place
 * that decision is made, so `isOverdue`, `isDueToday` and `dueMeta` cannot
 * disagree about the same row.
 */
function dayDelta(due: string | null, now: Date): number | null {
  if (!due) return null;
  const at = parseDueDate(due);
  if (!at) return null;
  return Math.round((startOfDay(at) - startOfDay(now)) / 86_400_000);
}

export function isOverdue(task: Task, now: Date): boolean {
  const days = dayDelta(task.due_date, now);
  return days !== null && days < 0;
}

export function isDueToday(task: Task, now: Date): boolean {
  return dayDelta(task.due_date, now) === 0;
}

/** What a due date means to a person: late, today, or a date. Not a raw ISO string. */
export function dueMeta(due: string | null, now: Date): Due | null {
  const days = dayDelta(due, now);
  const at = due === null ? null : parseDueDate(due);
  if (days === null || at === null) return null;

  if (days < 0) {
    return {
      label: days === -1 ? "1 day late" : `${Math.abs(days)} days late`,
      tone: "danger",
    };
  }
  if (days === 0) return { label: "Today", tone: "warning" };
  if (days === 1) return { label: "Tomorrow", tone: "muted" };
  if (days < 7) {
    return { label: at.toLocaleDateString("en-AU", { weekday: "short" }), tone: "muted" };
  }
  return { label: at.toLocaleDateString("en-AU", { day: "numeric", month: "short" }), tone: "muted" };
}

/** Due ascending, undated last, then by how much it matters. */
function dueTime(task: Task): number {
  if (!task.due_date) return Number.POSITIVE_INFINITY;
  const at = parseDueDate(task.due_date);
  return at ? at.getTime() : Number.POSITIVE_INFINITY;
}

export function sortTasksByDueDate(tasks: readonly Task[]): Task[] {
  return [...tasks].sort((a, b) => {
    const at = dueTime(a);
    const bt = dueTime(b);
    if (at !== bt) return at - bt;
    if (a.priority !== b.priority) return b.priority - a.priority;
    return a.created_at.localeCompare(b.created_at);
  });
}

/* ── Filters ──────────────────────────────────────────────────
   /tasks            all open tasks
   /tasks?filter=late   overdue open tasks
   /tasks?filter=today  open tasks due today

   Today's count chips call the same predicates with the same `now`, so a chip
   cannot promise a number its destination view does not show. */

export type TaskFilter = "all" | "late" | "today";

export function parseTaskFilter(raw: string | null | undefined): TaskFilter {
  return raw === "late" || raw === "today" ? raw : "all";
}

export function matchesTaskFilter(task: Task, filter: TaskFilter, now: Date): boolean {
  if (filter === "late") return isOverdue(task, now);
  if (filter === "today") return isDueToday(task, now);
  return true;
}
