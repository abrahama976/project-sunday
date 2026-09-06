"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";
type Notif = {
  id: string;
  title: string;
  body: string | null;
  read: boolean;
  created_at: string;
  type: "approval" | "notification";
  href?: string;
};
export default function NotificationPanel() {
  // Memoised: a fresh client on every render made it a changing dependency,
  // which is why the effect below had to lie about its dependency list.
  const supabase = useMemo(() => createClient(), []);
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Notif[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const panelRef = useRef<HTMLDivElement>(null);
  const loadNotifications = useCallback(async () => {
    const { data: { user } } = await supabase.auth.getUser();
    if (!user) return;
    const [resApprovals, resNotifs] = await Promise.all([
      supabase
        .from("action_queue")
        .select("id, action_type, payload, created_at")
        .eq("user_id", user.id)
        .eq("status", "awaiting_approval")
        .order("created_at", { ascending: false })
        .limit(10),
      supabase
        .from("notifications")
        .select("id, title, body, read, created_at")
        .eq("user_id", user.id)
        .order("created_at", { ascending: false })
        .limit(20),
    ]);
    const approvals: Notif[] = (resApprovals.data || []).map((a) => ({
      id: a.id,
      title: `Action: ${(a.action_type as string).replace(/_/g, " ")}`,
      body: null,
      read: false,
      created_at: a.created_at as string,
      type: "approval",
      href: "/approvals",
    }));
    const notifs: Notif[] = (resNotifs.data || []).map((n) => ({
      id: n.id,
      title: n.title as string,
      body: n.body as string | null,
      read: n.read as boolean,
      created_at: n.created_at as string,
      type: "notification",
    }));
    const all = [...approvals, ...notifs].sort(
      (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    );
    setItems(all);
    setUnreadCount(approvals.length + notifs.filter(n => !n.read).length);
  }, [supabase]);

  useEffect(() => {
    // Called through a function declared inside the effect: calling a
    // setState-containing one straight from an effect body is the cascading-
    // render pattern React now rejects.
    async function start() { await loadNotifications(); }
    void start();
    const channel = supabase.channel("notif-panel")
      .on("postgres_changes", { event: "*", schema: "public", table: "action_queue" }, () => void loadNotifications())
      .on("postgres_changes", { event: "INSERT", schema: "public", table: "notifications" }, () => void loadNotifications())
      .subscribe();
    return () => { supabase.removeChannel(channel); };
  }, [supabase, loadNotifications]);

  // A ticking clock rather than Date.now() inside the renderer below. Reading
  // the clock during render is impure — two renders can disagree — and it also
  // meant "3m ago" stayed "3m ago" until something else re-rendered the panel.
  const [now, setNow] = useState(0);
  useEffect(() => {
    const tick = () => setNow(Date.now());
    const soon = setTimeout(tick, 0);
    const every = setInterval(tick, 60000);
    return () => { clearTimeout(soon); clearInterval(every); };
  }, []);
  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);
  const markAllRead = async () => {
    const { data: { user } } = await supabase.auth.getUser();
    if (!user) return;
    await supabase.from("notifications").update({ read: true }).eq("user_id", user.id).eq("read", false);
    setItems(prev => prev.map(n => n.type === "notification" ? { ...n, read: true } : n));
    setUnreadCount(items.filter(n => n.type === "approval").length);
  };
  const relativeTime = (iso: string) => {
    if (!now) return "";
    const diff = now - new Date(iso).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    return `${Math.floor(hrs / 24)}d ago`;
  };
  return (
    <>
      {/* Bell button */}
      <button
        onClick={() => setOpen(v => !v)}
        style={{ position: "relative", padding: "var(--space-2)", lineHeight: 1 }}
        aria-label="Notifications"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.73 21a2 2 0 0 1-3.46 0" />
        </svg>
        {unreadCount > 0 && (
          <span style={{
            position: "absolute", top: 2, right: 2,
            width: 8, height: 8,
            borderRadius: "50%",
            background: "var(--color-danger)",
            border: "1.5px solid var(--color-bg)",
          }} />
        )}
      </button>
      {/* Slide-over panel */}
      {open && (
        <div style={{
          position: "fixed", inset: 0, zIndex: 100,
          background: "rgba(0,0,0,0.4)",
        }}>
          <div ref={panelRef} style={{
            position: "absolute", top: 0, right: 0,
            width: "min(340px, 100vw)",
            height: "100dvh",
            background: "var(--color-surface)",
            borderLeft: "1px solid var(--color-border)",
            display: "flex",
            flexDirection: "column",
          }}>
            {/* Header */}
            <div style={{
              padding: "var(--space-4) var(--space-5)",
              borderBottom: "1px solid var(--color-border)",
              display: "flex", justifyContent: "space-between", alignItems: "center",
            }}>
              <span style={{ fontWeight: 600, fontSize: "0.9375rem" }}>Notifications</span>
              <div style={{ display: "flex", gap: "var(--space-3)", alignItems: "center" }}>
                {unreadCount > 0 && (
                  <button onClick={markAllRead} style={{ fontSize: "0.75rem", color: "var(--color-primary)" }}>
                    Mark all read
                  </button>
                )}
                <button onClick={() => setOpen(false)} style={{ color: "var(--color-text-muted)", lineHeight: 1 }}>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M18 6 6 18M6 6l12 12"/></svg>
                </button>
              </div>
            </div>
            {/* List */}
            <div style={{ flex: 1, overflowY: "auto", padding: "var(--space-2) 0" }}>
              {items.length === 0 ? (
                <div style={{ padding: "var(--space-8)", textAlign: "center", color: "var(--color-text-faint)", fontSize: "0.875rem" }}>
                  All quiet
                </div>
              ) : (
                items.map((item) => {
                  const content = (
                    <div style={{
                      padding: "var(--space-3) var(--space-5)",
                      borderBottom: "1px solid var(--color-border)",
                      opacity: item.read ? 0.6 : 1,
                      display: "flex", flexDirection: "column", gap: "var(--space-1)",
                      background: item.read ? "transparent" : "var(--color-surface-2)",
                    }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "var(--space-2)" }}>
                        <span style={{ fontSize: "0.875rem", fontWeight: item.read ? 400 : 500, color: "var(--color-text)", flex: 1 }}>
                          {item.title}
                        </span>
                        {item.type === "approval" && (
                          <span style={{ fontSize: "0.6875rem", background: "var(--color-warning-faint)", color: "var(--color-warning)", padding: "2px 6px", borderRadius: "var(--radius-sm)", whiteSpace: "nowrap" }}>
                            Needs action
                          </span>
                        )}
                      </div>
                      {item.body && (
                        <span style={{ fontSize: "0.8125rem", color: "var(--color-text-muted)" }}>{item.body}</span>
                      )}
                      <span style={{ fontSize: "0.6875rem", color: "var(--color-text-faint)" }}>{relativeTime(item.created_at)}</span>
                    </div>
                  );
                  return item.href ? (
                    <Link key={item.id} href={item.href} style={{ textDecoration: "none", display: "block" }} onClick={() => setOpen(false)}>
                      {content}
                    </Link>
                  ) : (
                    <div key={item.id}>{content}</div>
                  );
                })
              )}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
