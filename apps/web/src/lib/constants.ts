// Web-side runtime constants. Mirrors values in apps/worker/config.py where relevant.
export const MAX_MESSAGES_LOADED = 100;
export const APPROVAL_HOLD_SECONDS = 5; // mirrors worker
export const ACTION_TIER_COLORS = {
  auto: "var(--color-success, #10b981)",
  approve: "var(--color-primary)",
  hold: "var(--color-danger, #ef4444)",
} as const;