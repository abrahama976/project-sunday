"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";

const MENU_ITEMS = [
  // First, because it is the only entry that is ever waiting on you. Until it
  // was added, write-tier actions queued to action_queue with no way to reach
  // them: /approvals existed but nothing in the app linked to it except the
  // bell and a Today card that only appears when the count is above zero.
  { href: "/approvals", label: "Approvals", desc: "Actions waiting for your OK", icon: "✅" },
  { href: "/schedule",  label: "Schedule",  desc: "Today's timeline and travel", icon: "📅" },
  { href: "/health",    label: "Health",    desc: "Water, meals, sleep logs",    icon: "🍎" },
  { href: "/traces",    label: "Traces",    desc: "How Sunday reached its answers", icon: "🔍" },
  { href: "/profile",   label: "Profile",   desc: "What the AI knows about you",  icon: "👤" },
  { href: "/settings",  label: "Settings",  desc: "Worker, notifications, account", icon: "⚙️" },
];

export default function MorePage() {
  // null means "not known yet, or the lookup failed". A count that silently
  // reads zero when the query failed is worse than no count at all — it says
  // there is nothing to approve, which is the exact bug this entry exists to
  // fix.
  const [pending, setPending] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;

    // Defined inside the effect on purpose: react-hooks/set-state-in-effect
    // flags a setState-containing function declared outside it, even an async
    // one. This is the same shape the traces page settled on.
    async function loadPending() {
      const supabase = createClient();
      const { data: { user } } = await supabase.auth.getUser();
      if (cancelled || !user) return;

      const { count, error } = await supabase
        .from("action_queue")
        .select("*", { count: "exact", head: true })
        .eq("user_id", user.id)
        .eq("status", "awaiting_approval");

      if (cancelled || error) return;
      setPending(count ?? 0);
    }

    void loadPending().catch(() => {
      /* Leave the count unknown; the row still renders its description. */
    });

    return () => { cancelled = true; };
  }, []);

  return (
    <div style={{ maxWidth: "800px", margin: "0 auto", padding: "var(--space-8) var(--space-6)" }}>
      <h1 style={{ fontSize: "1.125rem", fontWeight: 600, marginBottom: "var(--space-6)" }}>
        More
      </h1>
      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
        {MENU_ITEMS.map(({ href, label, desc, icon }) => {
          const waiting = href === "/approvals" && pending !== null && pending > 0;
          return (
            <Link
              key={href}
              href={href}
              style={{
                display: "flex",
                alignItems: "center",
                gap: "var(--space-4)",
                padding: "var(--space-4) var(--space-5)",
                background: "var(--color-surface)",
                border: waiting ? "1px solid var(--color-primary)" : "1px solid var(--color-border)",
                borderRadius: "var(--radius-lg)",
                textDecoration: "none",
                color: "var(--color-text)",
                transition: "background 150ms",
              }}
            >
              <span style={{ fontSize: "1.25rem", lineHeight: 1, flexShrink: 0 }}>{icon}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: "0.9375rem", fontWeight: 500 }}>{label}</div>
                <div style={{ fontSize: "0.75rem", color: "var(--color-text-muted)", marginTop: "2px" }}>
                  {waiting
                    ? `${pending} action${pending === 1 ? "" : "s"} waiting for your approval`
                    : desc}
                </div>
              </div>
              {waiting && (
                <span
                  aria-label={`${pending} pending`}
                  style={{
                    flexShrink: 0,
                    minWidth: "1.375rem",
                    padding: "0 var(--space-2)",
                    borderRadius: "999px",
                    background: "var(--color-primary)",
                    color: "var(--color-bg)",
                    fontSize: "0.75rem",
                    fontWeight: 600,
                    lineHeight: "1.375rem",
                    textAlign: "center",
                  }}
                >
                  {pending}
                </span>
              )}
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--color-text-faint)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="9 18 15 12 9 6" />
              </svg>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
