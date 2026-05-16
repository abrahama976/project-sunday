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

  // Subscribe-first, load-second, dedupe — fixes the race.
  useEffect(() => {
    let cancelled = false;
    const seen = new Set<string>();

    const channel = supabase
      .channel("messages-realtime")
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "messages" },
        (payload) => {
          const row = payload.new;
          if (!isMessage(row)) return;
          if (seen.has(row.id)) return;
          seen.add(row.id);
          setMessages((prev) => [...prev, row]);
        }
      )
      .subscribe();

    (async () => {
      const { data, error } = await supabase
        .from("messages")
        .select("*")
        .order("created_at", { ascending: true })
        .limit(MAX_MESSAGES_LOADED);

      if (cancelled) return;
      if (error) {
        setError(`Failed to load history: ${error.message}`);
        return;
      }
      if (data) {
        const valid = data.filter(isMessage);
        valid.forEach((m) => seen.add(m.id));
        setMessages(valid);
      }
    })();

    return () => {
      cancelled = true;
      supabase.removeChannel(channel);
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
      const { error: insertErr } = await supabase
        .from("messages")
        .insert({ role: "user", content: text, model_used: "user" });

      if (insertErr) throw insertErr;

      // Placeholder echo. Phase 3 worker will replace this.
      const { error: echoErr } = await supabase.from("messages").insert({
        role: "assistant",
        content:
          `Received: \`${text}\`\n\n` +
          `_The Mac worker is not yet connected. ` +
          `This will route to Gemini (and later Ollama for sensitive data) in Phase 3._`,
        model_used: "placeholder",
      });
      if (echoErr) throw echoErr;
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