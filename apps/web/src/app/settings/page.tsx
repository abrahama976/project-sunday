"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import SavedPlaces from "./places";

export default function SettingsPage() {
  const supabase = useMemo(() => createClient(), []);
  const router = useRouter();

  const [email, setEmail] = useState<string | null>(null);
  const [showConfirm, setShowConfirm] = useState(false);
  const [cleared, setCleared] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const fetchUser = async () => {
      const { data: { user } } = await supabase.auth.getUser();
      if (!cancelled && user?.email) {
        setEmail(user.email);
      }
    };
    void fetchUser();
    return () => { cancelled = true; };
  }, [supabase]);

  const handleSignOut = async () => {
    await supabase.auth.signOut();
    router.push("/login");
  };

  const handleClearHistory = async () => {
    setLoading(true);
    const { data: { user } } = await supabase.auth.getUser();
    if (user) {
      await supabase
        .from("messages")
        .update({ is_deleted: true })
        .eq("user_id", user.id);
      
      setCleared(true);
      setShowConfirm(false);
    }
    setLoading(false);
  };

  return (
    <div style={{ maxWidth: "800px", margin: "0 auto", padding: "var(--space-8) var(--space-6)" }}>
      <h1 style={{ fontSize: "1.125rem", fontWeight: 600, marginBottom: "var(--space-8)" }}>
        Settings
      </h1>

      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-8)" }}>
        
        {/* Account Section */}
        <section>
          <h2 style={{ fontSize: "0.8125rem", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--color-text-faint)", marginBottom: "var(--space-3)" }}>
            Account
          </h2>
          <div style={{ 
            background: "var(--color-surface)", 
            border: "1px solid var(--color-border)", 
            borderRadius: "var(--radius-lg)", 
            padding: "var(--space-4) var(--space-5)",
            display: "flex",
            flexDirection: "column",
            gap: "var(--space-4)"
          }}>
            <div>
              <div style={{ fontSize: "0.8125rem", color: "var(--color-text-muted)", marginBottom: "2px" }}>Signed in as</div>
              <div style={{ fontSize: "0.9375rem", color: "var(--color-text)", fontWeight: 500 }}>
                {email || "Loading..."}
              </div>
            </div>
            <button 
              onClick={() => void handleSignOut()}
              style={{
                alignSelf: "flex-start",
                padding: "var(--space-2) var(--space-4)",
                background: "var(--color-surface-2)",
                border: "1px solid var(--color-border)",
                borderRadius: "var(--radius-md)",
                fontSize: "0.875rem",
                color: "var(--color-text)",
                fontWeight: 500
              }}
            >
              Sign out
            </button>
          </div>
        </section>

        <SavedPlaces />

        {/* Worker Section */}
        <section>
          <h2 style={{ fontSize: "0.8125rem", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--color-text-faint)", marginBottom: "var(--space-3)" }}>
            Worker
          </h2>
          <div style={{ 
            background: "var(--color-surface)", 
            border: "1px solid var(--color-border)", 
            borderRadius: "var(--radius-lg)", 
            padding: "var(--space-4) var(--space-5)",
          }}>
            <p style={{ fontSize: "0.9375rem", color: "var(--color-text)" }}>
              Worker runs locally on your Mac. Restart it manually if it goes offline.
            </p>
          </div>
        </section>

        {/* Danger Zone */}
        <section>
          <h2 style={{ fontSize: "0.8125rem", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--color-danger)", marginBottom: "var(--space-3)" }}>
            Danger Zone
          </h2>
          <div style={{ 
            background: "var(--color-surface)", 
            border: "1px solid var(--color-danger)", 
            borderRadius: "var(--radius-lg)", 
            padding: "var(--space-4) var(--space-5)",
            display: "flex",
            flexDirection: "column",
            gap: "var(--space-4)"
          }}>
            {cleared ? (
              <div style={{ fontSize: "0.9375rem", color: "var(--color-success)", fontWeight: 500 }}>
                Chat history cleared.
              </div>
            ) : showConfirm ? (
              <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
                <div style={{ fontSize: "0.9375rem", color: "var(--color-text)" }}>
                  Are you sure? This cannot be undone.
                </div>
                <div style={{ display: "flex", gap: "var(--space-3)" }}>
                  <button 
                    onClick={() => void handleClearHistory()}
                    disabled={loading}
                    style={{
                      padding: "var(--space-2) var(--space-4)",
                      background: "var(--color-danger)",
                      color: "#fff",
                      border: "none",
                      borderRadius: "var(--radius-md)",
                      fontSize: "0.875rem",
                      fontWeight: 600,
                      opacity: loading ? 0.5 : 1
                    }}
                  >
                    Confirm
                  </button>
                  <button 
                    onClick={() => setShowConfirm(false)}
                    disabled={loading}
                    style={{
                      padding: "var(--space-2) var(--space-4)",
                      background: "transparent",
                      border: "1px solid var(--color-border)",
                      color: "var(--color-text)",
                      borderRadius: "var(--radius-md)",
                      fontSize: "0.875rem",
                      fontWeight: 500,
                      opacity: loading ? 0.5 : 1
                    }}
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <div>
                <button 
                  onClick={() => setShowConfirm(true)}
                  style={{
                    padding: "var(--space-2) var(--space-4)",
                    background: "rgba(196, 77, 77, 0.1)",
                    border: "1px solid var(--color-danger)",
                    color: "var(--color-danger)",
                    borderRadius: "var(--radius-md)",
                    fontSize: "0.875rem",
                    fontWeight: 600
                  }}
                >
                  Clear chat history
                </button>
              </div>
            )}
          </div>
        </section>

      </div>
    </div>
  );
}
