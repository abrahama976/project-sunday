"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { createClient } from "@/lib/supabase/client";

function LoginPageInner() {
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
      minHeight: "calc(100dvh - var(--nav-top-h))", padding: "var(--space-6)",
    }}>
      <div style={{
        width: "100%", maxWidth: "340px",
        display: "flex", flexDirection: "column", gap: "var(--space-4)",
      }}>
        <div style={{ marginBottom: "var(--space-2)" }}>
          <h1 style={{
            fontFamily: "var(--font-mono)",
            fontSize: "1rem", fontWeight: 500, color: "var(--color-primary)",
            marginBottom: "var(--space-1)",
          }}>
            Project Sunday
          </h1>
          <p style={{ fontSize: "0.8125rem", color: "var(--color-text-muted)" }}>
            Sign in to continue.
          </p>
        </div>

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
            color: "var(--color-danger)",
            background: "rgba(196, 77, 77, 0.08)",
            padding: "var(--space-3) var(--space-4)",
            borderRadius: "var(--radius-md)",
          }}>
            {error}
          </div>
        )}

        <button
          onClick={handleSubmit}
          disabled={loading || !email || !password}
          style={{
            background: "var(--color-primary)", color: "#fff", border: "none",
            borderRadius: "var(--radius-lg)", padding: "var(--space-3) var(--space-4)",
            fontSize: "0.9375rem", fontWeight: 500,
            cursor: loading || !email || !password ? "not-allowed" : "pointer",
            opacity: loading || !email || !password ? 0.5 : 1,
            transition: "opacity 150ms",
          }}
        >
          {loading ? "Signing in…" : "Sign in"}
        </button>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginPageInner />
    </Suspense>
  );
}

const inputStyle: React.CSSProperties = {
  background: "var(--color-surface-2)",
  border: "1px solid var(--color-border)",
  borderRadius: "var(--radius-lg)",
  padding: "var(--space-3) var(--space-4)",
  color: "var(--color-text)",
  fontSize: "0.9375rem",
  outline: "none",
};