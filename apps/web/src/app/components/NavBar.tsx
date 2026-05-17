"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV = [
  { href: "/", label: "Chat", icon: "💬" },
  { href: "/approvals", label: "Approvals", icon: "✅" },
  { href: "/inventory", label: "Inventory", icon: "📦" },
  { href: "/dashboard", label: "Dashboard", icon: "📊" },
];

export default function NavBar() {
  const pathname = usePathname();
  return (
    <>
      {/* Top bar — brand name only */}
      <nav style={{
        display: "flex",
        alignItems: "center",
        borderBottom: "1px solid var(--color-border)",
        background: "var(--color-surface)",
        padding: "0 1.25rem",
        position: "sticky",
        top: 0,
        zIndex: 50,
        height: "52px",
        flexShrink: 0,
      }}>
        <span style={{
          fontWeight: 600,
          color: "var(--color-primary)",
          letterSpacing: "-0.02em",
          fontSize: "1rem",
        }}>
          Project Sunday
        </span>
      </nav>

      {/* Bottom tab bar */}
      <nav style={{
        display: "flex",
        position: "fixed",
        bottom: 0,
        left: 0,
        right: 0,
        zIndex: 50,
        background: "var(--color-surface)",
        borderTop: "1px solid var(--color-border)",
        height: "60px",
        alignItems: "stretch",
      }}>
        {NAV.map(({ href, label, icon }) => {
          const active = pathname === href;
          return (
            <Link
              key={href}
              href={href}
              style={{
                flex: 1,
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                gap: "2px",
                textDecoration: "none",
                color: active ? "var(--color-primary)" : "var(--color-text-muted)",
                fontSize: "0.625rem",
                fontWeight: active ? 600 : 400,
                borderTop: active ? "2px solid var(--color-primary)" : "2px solid transparent",
                transition: "color 150ms",
              }}
            >
              <span style={{ fontSize: "1.25rem", lineHeight: 1 }}>{icon}</span>
              {label}
            </Link>
          );
        })}
      </nav>
    </>
  );
}
