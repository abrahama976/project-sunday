"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { createClient } from "@/lib/supabase/client";
import { MAX_MESSAGES_LOADED } from "@/lib/constants";

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  model_used: string | null;
  created_at: string;
};

function isMessage(x: unknown): x is Message {
  if (!x || typeof x !== "object") return false;
  const o = x as Record<string, unknown>;
  return (
    typeof o.id === "string" &&
    (o.role === "user" || o.role === "assistant") &&
    typeof o.content === "string" &&
    (o.model_used === null || typeof o.model_used === "string") &&
    typeof o.created_at === "string"
  );
}

/* ── Timestamp formatter ────────────────────────────────── */
function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "";
  }
}

/* ── Thinking indicator ─────────────────────────────────── */
function ThinkingDot() {
  return (
    <div style={{
      display: "flex",
      alignItems: "center",
      gap: "var(--space-3)",
      padding: "var(--space-3) 0",
    }}>
      <span style={{
        width: 6,
        height: 6,
        borderRadius: "50%",
        background: "var(--color-primary)",
        animation: "pulse-dot 1.4s ease-in-out infinite",
        flexShrink: 0,
      }} />
      <span style={{
        fontSize: "0.8125rem",
        color: "var(--color-text-faint)",
      }}>
        Thinking…
      </span>
      <style>{`
        @keyframes pulse-dot {
          0%, 100% { opacity: 0.3; transform: scale(0.85); }
          50% { opacity: 1; transform: scale(1); }
        }
      `}</style>
    </div>
  );
}

/* ── Message row ────────────────────────────────────────── */
function MessageRow({ msg }: { msg: Message }) {
  const [showTime, setShowTime] = useState(false);
  const isUser = msg.role === "user";

  return (
    <div
      onClick={() => setShowTime((v) => !v)}
      style={{
        display: "flex",
        gap: "var(--space-3)",
        padding: "var(--space-2) 0",
        cursor: "default",
      }}
    >
      {/* Accent bar for user messages */}
      <div style={{
        width: 2,
        flexShrink: 0,
        borderRadius: 1,
        background: isUser ? "var(--color-primary)" : "transparent",
        marginTop: 2,
        marginBottom: 2,
      }} />

      <div style={{ flex: 1, minWidth: 0 }}>
        {/* Role label */}
        <div style={{
          display: "flex",
          alignItems: "baseline",
          gap: "var(--space-2)",
          marginBottom: "var(--space-1)",
        }}>
          <span style={{
            fontSize: "0.75rem",
            fontWeight: 600,
            color: isUser ? "var(--color-primary)" : "var(--color-text-muted)",
            letterSpacing: "0.02em",
            textTransform: "uppercase",
          }}>
            {isUser ? "You" : "Sunday"}
          </span>
          {/* Timestamp — shown on tap (mobile) */}
          <span style={{
            fontSize: "0.6875rem",
            color: "var(--color-text-faint)",
            opacity: showTime ? 1 : 0,
            transition: "opacity 150ms",
          }}>
            {formatTime(msg.created_at)}
          </span>
          {!isUser && msg.model_used && msg.model_used !== "system" && (
            <span style={{
              fontSize: "0.6875rem",
              color: "var(--color-text-faint)",
              marginLeft: "auto",
              opacity: showTime ? 1 : 0,
              transition: "opacity 150ms",
            }}>
              {msg.model_used}
            </span>
          )}
        </div>

        {/* Content */}
        <div className="markdown-body" style={{
          color: isUser ? "var(--color-text)" : "var(--color-text)",
          fontSize: "0.9375rem",
        }}>
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {msg.content}
          </ReactMarkdown>
        </div>
      </div>
    </div>
  );
}

/* ── Chat page ──────────────────────────────────────────── */
export default function ChatPage() {
  // Stable client instance — avoids reconstructing on every render.
  const supabase = useMemo(() => createClient(), []);

  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [userName, setUserName] = useState("");
  const [userId, setUserId] = useState<string | null>(null);
  const [workerOffline, setWorkerOffline] = useState(false);
  const [connStatus, setConnStatus] = useState<"connected" | "reconnecting" | "error">("reconnecting");
  const offlineTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const channelRef = useRef<ReturnType<typeof supabase.channel> | null>(null);

  const clearOfflineTimer = () => {
    if (offlineTimerRef.current) {
      clearTimeout(offlineTimerRef.current);
      offlineTimerRef.current = null;
    }
    setWorkerOffline(false);
  };

  useEffect(() => {
    (async () => {
      const { data: { user } } = await supabase.auth.getUser();
      if (user) setUserId(user.id);

      const { data: profile } = await supabase
        .from("user_profile")
        .select("content")
        .limit(1)
        .maybeSingle();
      if (profile?.content) {
        const match = profile.content.match(/^#\s+(.+)/m);
        if (match) { setUserName(match[1].trim()); return; }
      }
      if (user?.email) setUserName(user.email.split("@")[0]);
    })();
  }, [supabase]);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    let cancelled = false;
    const seen = new Set<string>();

    const mergeMessages = (rows: Message[]) => {
      setMessages((prev) => {
        const byId = new Map<string, Message>();
        for (const m of prev) byId.set(m.id, m);
        for (const m of rows) {
          seen.add(m.id);
          byId.set(m.id, m);
        }
        return Array.from(byId.values()).sort((a, b) =>
          a.created_at.localeCompare(b.created_at)
        );
      });
    };

    const appendMessage = (row: Message) => {
      if (seen.has(row.id)) return;
      seen.add(row.id);
      mergeMessages([row]);
    };

    const loadHistory = async () => {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user || cancelled) return;
      const { data, error: loadErr } = await supabase
        .from("messages")
        .select("*")
        .eq("user_id", user.id)
        .order("created_at", { ascending: true })
        .limit(MAX_MESSAGES_LOADED);

      if (cancelled) return;
      if (loadErr) {
        setError(`Failed to load history: ${loadErr.message}`);
        return;
      }
      if (data) {
        mergeMessages(data.filter(isMessage));
        // Clear offline warning if new assistant messages arrived via poll
        if (data?.some((m: unknown) => isMessage(m) && (m as Message).role === "assistant")) {
          clearOfflineTimer();
        }
      }
    };

    // RLS-filtered Realtime requires the user JWT on the socket.
    const { data: authListener } = supabase.auth.onAuthStateChange(
      (_event, session) => {
        if (session?.access_token) {
          supabase.realtime.setAuth(session.access_token);
        }
      }
    );

    let pollInterval: number | undefined;

    const setupRealtimeChannel = async () => {
      if (cancelled) return;
      if (channelRef.current) {
        supabase.removeChannel(channelRef.current);
        channelRef.current = null;
      }
      const { data: { session } } = await supabase.auth.getSession();
      if (cancelled) return;
      if (session?.access_token) {
        await supabase.realtime.setAuth(session.access_token);
      }

      const channel = supabase.channel("messages-realtime");
      channelRef.current = channel;

      channel
        .on(
          "postgres_changes",
          { event: "INSERT", schema: "public", table: "messages" },
          (payload) => {
            const row = payload.new;
            if (!isMessage(row)) return;
            appendMessage(row);
            if (row.role === "assistant") clearOfflineTimer();
          }
        )
        .on('system', { event: 'disconnect' }, () => {
          if (cancelled) return;
          setConnStatus("reconnecting");
          setTimeout(() => {
            if (!cancelled) setupRealtimeChannel();
          }, 3000);
        })
        .subscribe((status, err) => {
          if (cancelled) return;
          if (status === "SUBSCRIBED") {
            setConnStatus("connected");
            void loadHistory();
          } else if (status === "CHANNEL_ERROR" || status === "TIMED_OUT") {
            setConnStatus("error");
            setError(`Realtime unavailable: ${err?.message ?? status}. Refresh to see new messages.`);
            void loadHistory();
          }
        });
    };

    void setupRealtimeChannel();

      // Polling fallback: re-fetch every 4s in case Realtime drops assistant messages
      pollInterval = setInterval(() => {
        void loadHistory();
      }, 4000) as unknown as number;
    // End of setupRealtimeChannel


    return () => {
      cancelled = true;
      clearInterval(pollInterval);
      authListener.subscription.unsubscribe();
      if (channelRef.current) supabase.removeChannel(channelRef.current);
    };
  }, [supabase]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  /* Auto-resize textarea */
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 120) + "px";
  }, [input]);

  const send = async () => {
    if (!input.trim() || loading) return;
    const text = input.trim();
    setInput("");
    setLoading(true);
    setError(null);

    try {
      const { data: { user } } = await supabase.auth.getUser();
      if (!user) throw new Error("Not authenticated");
      const { data, error: insertErr } = await supabase
        .from("messages")
        .insert({ role: "user", content: text, model_used: "user", user_id: user.id })
        .select()
        .single();

      if (insertErr) throw insertErr;
      // Show the user message immediately; worker reply arrives via Realtime.
      if (data && isMessage(data)) {
        setMessages((prev) => {
          if (prev.some((m) => m.id === data.id)) return prev;
          return [...prev, data].sort((a, b) =>
            a.created_at.localeCompare(b.created_at)
          );
        });
      }
      offlineTimerRef.current = setTimeout(() => setWorkerOffline(true), 12000);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "unknown error";
      setError(`Send failed: ${msg}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      display: "flex",
      flexDirection: "column",
      height: "calc(100dvh - var(--nav-top-h))",
      paddingBottom: "calc(var(--nav-bottom-h) + var(--safe-area-bottom))",
    }}>
      {/* Header with status */}
      <div style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        padding: "var(--space-2) var(--space-4)",
      }}>
        <button
          onClick={async () => {
            if (userId) {
              await supabase.from("messages").delete().eq("user_id", userId);
              setMessages([]);
            }
          }}
          style={{
            background: "transparent",
            border: "none",
            color: "var(--color-text-faint)",
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: "var(--space-1)",
          }}
          title="Clear Chat"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="3 6 5 6 21 6" />
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
          </svg>
        </button>
        
        <div style={{
          display: "flex",
          alignItems: "center",
          fontSize: "0.6875rem",
          color: "var(--color-text-faint)",
          gap: "6px",
        }}>
          {connStatus === "reconnecting" ? "Reconnecting..." : connStatus === "connected" ? "Connected" : "Offline"}
          <span style={{
            width: 6,
            height: 6,
            borderRadius: "50%",
            background: connStatus === "connected" ? "var(--color-success, #6daa45)" : connStatus === "reconnecting" ? "var(--color-warning, #e8a020)" : "var(--color-danger, #c44d4d)",
            display: "inline-block"
          }} />
        </div>
      </div>

      {/* Message stream */}
      <div style={{
        flex: 1,
        overflowY: "auto",
        padding: "0 var(--space-5) var(--space-4) var(--space-5)",
        display: "flex",
        flexDirection: "column",
      }}>
        {messages.length === 0 && !error && (
          <div style={{
            margin: "auto",
            textAlign: "center",
            color: "var(--color-text-faint)",
            paddingTop: "4rem",
          }}>
            <div style={{
              fontFamily: "var(--font-mono)",
              fontSize: "1.5rem",
              color: "var(--color-primary)",
              marginBottom: "var(--space-4)",
              opacity: 0.7,
            }}>◈</div>
            <p style={{ fontSize: "1rem", color: "var(--color-text-muted)", fontWeight: 500 }}>
              {userName ? `Hey, ${userName}.` : "Hey there."}
            </p>
            <p style={{ fontSize: "0.8125rem", marginTop: "var(--space-2)" }}>
              What are we working on?
            </p>
          </div>
        )}

        {messages.map((msg) => (
          <MessageRow key={msg.id} msg={msg} />
        ))}

        {loading && <ThinkingDot />}
        
        {workerOffline && (
          <div style={{
            fontSize: "0.8125rem",
            color: "var(--color-text-faint)",
            padding: "var(--space-2) 0",
            textAlign: "center",
          }}>
            Worker appears offline — message queued, will respond when reconnected.
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Error bar */}
      {error && (
        <div style={{
          padding: "var(--space-2) var(--space-5)",
          background: "rgba(196, 77, 77, 0.08)",
          color: "var(--color-danger)",
          fontSize: "0.8125rem",
          borderTop: "1px solid var(--color-border)",
        }}>
          {error}
        </div>
      )}

      {/* Input bar */}
      <div style={{
        padding: "var(--space-3) var(--space-5)",
        borderTop: "1px solid var(--color-border)",
        background: "var(--color-surface)",
        display: "flex",
        alignItems: "flex-end",
        gap: "var(--space-3)",
      }}>
        <textarea
          ref={textareaRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            // Guard IME composition (Japanese/Chinese/Korean input)
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              send();
            }
          }}
          placeholder="Message Sunday…"
          rows={1}
          style={{
            flex: 1,
            background: "var(--color-surface-2)",
            border: "1px solid var(--color-border)",
            borderRadius: "var(--radius-lg)",
            padding: "var(--space-3) var(--space-4)",
            color: "var(--color-text)",
            resize: "none",
            lineHeight: 1.5,
            fontSize: "0.9375rem",
            outline: "none",
            maxHeight: "120px",
            overflowY: "auto",
          }}
        />
        <button
          onClick={send}
          disabled={loading || !input.trim()}
          aria-label="Send message"
          style={{
            width: 36,
            height: 36,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            background: loading || !input.trim() ? "transparent" : "var(--color-primary)",
            border: loading || !input.trim() ? "1px solid var(--color-border)" : "none",
            borderRadius: "var(--radius-md)",
            opacity: loading || !input.trim() ? 0.4 : 1,
            transition: "opacity 150ms, background 150ms",
            cursor: loading || !input.trim() ? "not-allowed" : "pointer",
            flexShrink: 0,
          }}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none"
            stroke={loading || !input.trim() ? "var(--color-text-faint)" : "#fff"}
            strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="22" y1="2" x2="11" y2="13" />
            <polygon points="22 2 15 22 11 13 2 9 22 2" />
          </svg>
        </button>
      </div>
    </div>
  );
}
