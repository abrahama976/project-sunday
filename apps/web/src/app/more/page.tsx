"use client";
import Link from "next/link";

const MENU_ITEMS = [
  { href: "/schedule",  label: "Schedule",  desc: "Today's timeline and travel", icon: "📅" },
  { href: "/health",    label: "Health",    desc: "Water, meals, sleep logs",    icon: "🍎" },
  { href: "/inventory", label: "Inventory", desc: "Groceries, pantry, supplies",  icon: "📦" },
  { href: "/profile",   label: "Profile",   desc: "What the AI knows about you",  icon: "👤" },
  { href: "/settings",  label: "Settings",  desc: "Worker, notifications, account", icon: "⚙️" },
];

export default function MorePage() {
  return (
    <div style={{ maxWidth: "800px", margin: "0 auto", padding: "var(--space-8) var(--space-6)" }}>
      <h1 style={{ fontSize: "1.125rem", fontWeight: 600, marginBottom: "var(--space-6)" }}>
        More
      </h1>
      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
        {MENU_ITEMS.map(({ href, label, desc, icon }) => (
          <Link
            key={href}
            href={href}
            style={{
              display: "flex",
              alignItems: "center",
              gap: "var(--space-4)",
              padding: "var(--space-4) var(--space-5)",
              background: "var(--color-surface)",
              border: "1px solid var(--color-border)",
              borderRadius: "var(--radius-lg)",
              textDecoration: "none",
              color: "var(--color-text)",
              transition: "background 150ms",
            }}
          >
            <span style={{ fontSize: "1.25rem", lineHeight: 1, flexShrink: 0 }}>{icon}</span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: "0.9375rem", fontWeight: 500 }}>{label}</div>
              <div style={{ fontSize: "0.75rem", color: "var(--color-text-muted)", marginTop: "2px" }}>{desc}</div>
            </div>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--color-text-faint)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="9 18 15 12 9 6" />
            </svg>
          </Link>
        ))}
      </div>
    </div>
  );
}
