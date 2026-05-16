"use client";

import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { createClient } from "@/lib/supabase/client";

export default function LoginPage() {
  const router = useRouter();
  const search = useSearchParams();
  const next = search.get("next") || "/";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async () => {
    if (loading) return;
    setLoading(true);
    setError(null);

    const supabase = createClient();
    const { error: authError } = await supabase.auth.signInWithPassword({
      email,
      password,
    });

    if (authError) {
      setError(authError.message);
      setLoading(false);
      return;
    }

    router.push(next);
    router.refresh();
  };

  return (
    <div style={{
      display: "flex", alignItems: "center", justifyContent: "center",
      minHeight: "calc(100dvh - 56px)", padding: "1.5rem",
    }}>
      <div style={{
        width: "100%", maxWidth: "360px",
        background: "var(--color-surface)",
        border: "1px solid var(--color-border)",
        borderRadius: "var(--radius-lg)", padding: "2rem",
        display: "flex", flexDirection: "column", gap: "1rem",
      }}>
        <h1 style={{ fontSize: "1.25rem", fontWeight: 500, margin: 0 }}>
          Project Sunday
        </h1>
        <p style={{ fontSize: "0.875rem", color: "var(--color-text-muted)", margin: 0 }}>
          Sign in to continue.
        </p>

        <input
          type="email"
          autoComplete="email"
          placeholder="Email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          style={inputStyle}
        />
        <input
          type="password"
          autoComplete="current-password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") handleSubmit();
          }}
          style={inputStyle}
        />

        {error && (
          <div style={{
            fontSize: "0.8125rem",
            color: "var(--color-danger, #ef4444)",
            background: "rgba(239,68,68,0.08)",
            padding: "0.5rem 0.75rem",
            borderRadius: "var(--radius-md, 0.5rem)",
          }}>
            {error}
          </div>
        )}

        <button
          onClick={handleSubmit}
          disabled={loading || !email || !password}
          style={{
            background: "var(--color-primary)", color: "#fff", border: "none",
            borderRadius: "var(--radius-lg)", padding: "0.75rem 1rem",
            fontSize: "0.9375rem", fontWeight: 500,
            cursor: loading || !email || !password ? "not-allowed" : "pointer",
            opacity: loading || !email || !password ? 0.5 : 1,
          }}
        >
          {loading ? "Signing in…" : "Sign in"}
        </button>
      </div>
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  background: "var(--color-surface-2)",
  border: "1px solid var(--color-border)",
  borderRadius: "var(--radius-lg)",
  padding: "0.625rem 0.875rem",
  color: "var(--color-text)",
  fontSize: "0.9375rem",
  outline: "none",
};