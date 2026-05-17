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

export default function ChatPage() {
  // Stable client instance — avoids reconstructing on every render.
  const supabase = useMemo(() => createClient(), []);

  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

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
      const { data, error: loadErr } = await supabase
        .from("messages")
        .select("*")
        .order("created_at", { ascending: true })
        .limit(MAX_MESSAGES_LOADED);

      if (cancelled) return;
      if (loadErr) {
        setError(`Failed to load history: ${loadErr.message}`);
        return;
      }
      if (data) mergeMessages(data.filter(isMessage));
    };

    // RLS-filtered Realtime requires the user JWT on the socket.
    const { data: authListener } = supabase.auth.onAuthStateChange(
      (_event, session) => {
        if (session?.access_token) {
          supabase.realtime.setAuth(session.access_token);
        }
      }
    );

    let channel: ReturnType<typeof supabase.channel> | null = null;

    void (async () => {
      const {
        data: { session },
      } = await supabase.auth.getSession();
      if (cancelled) return;
      if (session?.access_token) {
        await supabase.realtime.setAuth(session.access_token);
      }

      channel = supabase
        .channel("messages-realtime")
        .on(
          "postgres_changes",
          { event: "INSERT", schema: "public", table: "messages" },
          (payload) => {
            const row = payload.new;
            if (!isMessage(row)) return;
            appendMessage(row);
          }
        )
        .subscribe((status, err) => {
          if (cancelled) return;
          if (status === "SUBSCRIBED") {
            void loadHistory();
          } else if (status === "CHANNEL_ERROR" || status === "TIMED_OUT") {
            setError(
              `Realtime unavailable: ${err?.message ?? status}. Refresh to see new messages.`
            );
            void loadHistory();
          }
        });
    })();

    return () => {
      cancelled = true;
      authListener.subscription.unsubscribe();
      if (channel) supabase.removeChannel(channel);
    };
  }, [supabase]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = async () => {
    if (!input.trim() || loading) return;
    const text = input.trim();
    setInput("");
    setLoading(true);
    setError(null);

    try {
      const { data, error: insertErr } = await supabase
        .from("messages")
        .insert({ role: "user", content: text, model_used: "user" })
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
    } catch (e) {
      const msg = e instanceof Error ? e.message : "unknown error";
      setError(`Send failed: ${msg}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "calc(100dvh - 56px)" }}>
      <div
        style={{
          flex: 1,
          overflowY: "auto",
          padding: "1.5rem",
          display: "flex",
          flexDirection: "column",
          gap: "1rem",
        }}
      >
        {messages.length === 0 && !error && (
          <div
            style={{
              margin: "auto",
              textAlign: "center",
              color: "var(--color-text-faint)",
              paddingTop: "4rem",
            }}
          >
            <div style={{ fontSize: "2rem", marginBottom: "1rem" }}>◈</div>
            <p style={{ fontSize: "1.125rem", color: "var(--color-text-muted)" }}>
              Hi, Alstone.
            </p>
            <p style={{ fontSize: "0.875rem", marginTop: "0.5rem" }}>
              Project Sunday is ready. What are we working on?
            </p>
          </div>
        )}

        {messages.map((msg) => (
          <div
            key={msg.id}
            style={{
              display: "flex",
              justifyContent: msg.role === "user" ? "flex-end" : "flex-start",
            }}
          >
            <div
              style={{
                maxWidth: "72ch",
                padding: "0.75rem 1rem",
                borderRadius:
                  msg.role === "user"
                    ? "1rem 1rem 0.25rem 1rem"
                    : "1rem 1rem 1rem 0.25rem",
                background:
                  msg.role === "user"
                    ? "var(--color-primary)"
                    : "var(--color-surface-offset)",
                color: msg.role === "user" ? "#fff" : "var(--color-text)",
                fontSize: "0.9375rem",
                lineHeight: 1.6,
                boxShadow: "var(--shadow-md)",
              }}
            >
              <div className="markdown-body">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {msg.content}
                </ReactMarkdown>
              </div>
              {msg.model_used && msg.role === "assistant" && (
                <span
                  style={{
                    display: "block",
                    marginTop: "0.5rem",
                    fontSize: "0.75rem",
                    color: "var(--color-text-faint)",
                  }}
                >
                  via {msg.model_used}
                </span>
              )}
            </div>
          </div>
        ))}

        {loading && (
          <div style={{ display: "flex", justifyContent: "flex-start" }}>
            <div
              style={{
                padding: "0.75rem 1rem",
                borderRadius: "1rem 1rem 1rem 0.25rem",
                background: "var(--color-surface-offset)",
                color: "var(--color-text-muted)",
                fontSize: "0.875rem",
              }}
            >
              Thinking…
            </div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {error && (
        <div
          style={{
            padding: "0.5rem 1.5rem",
            background: "rgba(239,68,68,0.08)",
            color: "var(--color-danger, #ef4444)",
            fontSize: "0.8125rem",
            borderTop: "1px solid var(--color-border)",
          }}
        >
          {error}
        </div>
      )}

      <div
        style={{
          padding: "0.75rem 1.5rem",
          borderTop: "1px solid var(--color-border)",
          background: "var(--color-surface)",
          display: "flex",
          gap: "0.75rem",
        }}
      >
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            // Guard IME composition (Japanese/Chinese/Korean input)
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              send();
            }
          }}
          placeholder="Message Project Sunday… (Enter to send, Shift+Enter for new line)"
          rows={1}
          style={{
            flex: 1,
            background: "var(--color-surface-2)",
            border: "1px solid var(--color-border)",
            borderRadius: "var(--radius-lg)",
            padding: "0.75rem 1rem",
            color: "var(--color-text)",
            resize: "none",
            lineHeight: 1.5,
            fontSize: "0.9375rem",
            outline: "none",
          }}
        />
        <button
          onClick={send}
          disabled={loading || !input.trim()}
          style={{
            background: "var(--color-primary)",
            color: "#fff",
            border: "none",
            borderRadius: "var(--radius-lg)",
            padding: "0 1.25rem",
            fontWeight: 500,
            fontSize: "0.875rem",
            opacity: loading || !input.trim() ? 0.5 : 1,
            transition: "opacity 180ms, background 180ms",
            cursor: loading || !input.trim() ? "not-allowed" : "pointer",
          }}
        >
          Send
        </button>
      </div>
    </div>
  );
}