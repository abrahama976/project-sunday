"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV = [
  { href: "/", label: "Chat" },
  { href: "/approvals", label: "Approvals" },
  { href: "/inventory", label: "Inventory" },
  { href: "/dashboard", label: "Dashboard" },
];

export default function NavBar() {
  const pathname = usePathname();
  return (
    <nav style={{
      display: "flex", alignItems: "center",
      borderBottom: "1px solid var(--color-border)",
      background: "var(--color-surface)",
      padding: "0 1.5rem",
      position: "sticky", top: 0, zIndex: 50, height: "56px"
    }}>
      <span style={{ fontWeight: 600, color: "var(--color-primary)", marginRight: "auto", letterSpacing: "-0.02em" }}>
        Project Sunday
      </span>
      {NAV.map(({ href, label }) => (
        <Link key={href} href={href} style={{
          padding: "0 1rem",
          height: "56px",
          display: "flex",
          alignItems: "center",
          color: pathname === href ? "var(--color-text)" : "var(--color-text-muted)",
          textDecoration: "none",
          fontSize: "0.875rem",
          borderBottom: pathname === href ? "2px solid var(--color-primary)" : "2px solid transparent",
          transition: "color 180ms",
        }}>
          {label}
        </Link>
      ))}
    </nav>
  );
}