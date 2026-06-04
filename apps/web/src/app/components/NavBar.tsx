"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { createClient } from "@/lib/supabase/client";

/* ── Tab definitions ──────────────────────────────────────── */
const TABS = [
  { href: "/",          label: "Today",   icon: "today"   },
  { href: "/chat",      label: "Chat",    icon: "chat"    },
  { href: "/tasks",     label: "Tasks",   icon: "tasks"   },
  { href: "/approvals", label: "Approve", icon: "approve" },
  { href: "/more",      label: "More",    icon: "more"    },
] as const;

/* ── Minimal SVG icons (16×16, stroke-based) ──────────────── */
function TabIcon({ name, active }: { name: string; active: boolean }) {
  const stroke = active ? "var(--color-primary)" : "currentColor";
  const props = { width: 20, height: 20, viewBox: "0 0 24 24", fill: "none", stroke, strokeWidth: 1.75, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };

  switch (name) {
    case "chat":
      return (
        <svg {...props}>
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
        </svg>
      );
    case "today":
      return (
        <svg {...props}>
          <circle cx="12" cy="12" r="10" />
          <polyline points="12 6 12 12 16 14" />
        </svg>
      );
    case "tasks":
      return (
        <svg {...props}>
          <polyline points="9 11 12 14 22 4" />
          <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
        </svg>
      );
    case "approve":
      return (
        <svg {...props}>
          <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
        </svg>
      );
    case "more":
      return (
        <svg {...props}>
          <line x1="3" y1="12" x2="21" y2="12" />
          <line x1="3" y1="6" x2="21" y2="6" />
          <line x1="3" y1="18" x2="21" y2="18" />
        </svg>
      );
    default:
      return null;
  }
}

/* ── Pending approval count badge ─────────────────────────── */
function usePendingCount() {
  const supabase = useMemo(() => createClient(), []);
  const [count, setCount] = useState(0);

  useEffect(() => {
    let cancelled = false;

    const fetchCount = async () => {
      const { count: c, error } = await supabase
        .from("action_queue")
        .select("*", { count: "exact", head: true })
        .eq("status", "awaiting_approval")
        .neq("tier", "auto");
      if (!cancelled && !error && c !== null) setCount(c);
    };

    void fetchCount();

    const channel = supabase
      .channel("nav-approval-count")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "action_queue" },
        () => { void fetchCount(); }
      )
      .subscribe();

    return () => {
      cancelled = true;
      supabase.removeChannel(channel);
    };
  }, [supabase]);

  return count;
}

/* ── NavBar Component ─────────────────────────────────────── */
export default function NavBar() {
  const pathname = usePathname();
  const pendingCount = usePendingCount();

  // Hide nav on login page
  if (pathname === "/login") return null;

  return (
    <>
      {/* Top bar */}
      <header style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        borderBottom: "1px solid var(--color-border)",
        background: "var(--color-surface)",
        padding: "0 var(--space-5)",
        position: "sticky",
        top: 0,
        zIndex: 50,
        height: "var(--nav-top-h)",
        flexShrink: 0,
      }}>
        <span style={{
          fontFamily: "var(--font-mono)",
          fontWeight: 500,
          color: "var(--color-primary)",
          letterSpacing: "-0.02em",
          fontSize: "0.875rem",
        }}>
          Project Sunday
        </span>
      </header>

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
        height: "calc(var(--nav-bottom-h) + var(--safe-area-bottom))",
        paddingBottom: "var(--safe-area-bottom)",
        alignItems: "stretch",
      }}>
        {TABS.map(({ href, label, icon }) => {
          const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
          const showBadge = icon === "approve" && pendingCount > 0;

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
                color: active ? "var(--color-primary)" : "var(--color-text-faint)",
                fontSize: "0.625rem",
                fontWeight: active ? 600 : 400,
                letterSpacing: "0.01em",
                position: "relative",
                transition: "color 150ms",
                WebkitTapHighlightColor: "transparent",
              }}
            >
              <span style={{ position: "relative", display: "flex" }}>
                <TabIcon name={icon} active={active} />
                {showBadge && (
                  <span style={{
                    position: "absolute",
                    top: -4,
                    right: -6,
                    minWidth: "15px",
                    height: "15px",
                    borderRadius: "9999px",
                    background: "var(--color-danger)",
                    color: "#fff",
                    fontSize: "0.5625rem",
                    fontWeight: 700,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    padding: "0 3px",
                    lineHeight: 1,
                  }}>
                    {pendingCount > 9 ? "9+" : pendingCount}
                  </span>
                )}
              </span>
              {label}
            </Link>
          );
        })}
      </nav>
    </>
  );
}
