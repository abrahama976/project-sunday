"use client";

import { useEffect, useMemo, useState } from "react";
import { createClient } from "@/lib/supabase/client";

type InventoryItem = {
  id: string;
  item: string;
  quantity: number;
  unit: string | null;
  expiry_date: string | null;
  category: string | null;
};

export default function InventoryPage() {
  const supabase = useMemo(() => createClient(), []);
  const [items, setItems] = useState<InventoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [editingId, setEditingId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const fetchInventory = async () => {
      setLoading(true);
      const { data } = await supabase
        .from("inventory")
        .select("*")
        .order("category", { ascending: true })
        .order("item", { ascending: true });

      if (!cancelled && data) {
        setItems(data);
        setLoading(false);
      }
    };

    void fetchInventory();

    const channel = supabase.channel("inventory_changes")
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "inventory" },
        () => {
          if (!cancelled) void fetchInventory();
        }
      )
      .subscribe();

    return () => {
      cancelled = true;
      supabase.removeChannel(channel);
    };
  }, [supabase]);

  const updateQuantity = async (id: string, newQty: number) => {
    if (newQty < 0) newQty = 0;
    
    // optimistic update
    setItems(prev => prev.map(item => item.id === id ? { ...item, quantity: newQty } : item));

    await supabase
      .from("inventory")
      .update({ quantity: newQty, updated_at: new Date().toISOString() })
      .eq("id", id);
  };

  const grouped = items.reduce((acc, item) => {
    const cat = item.category || "Uncategorized";
    if (!acc[cat]) acc[cat] = [];
    acc[cat].push(item);
    return acc;
  }, {} as Record<string, InventoryItem[]>);

  const categories = Object.keys(grouped).sort();

  return (
    <div style={{ maxWidth: "800px", margin: "0 auto", padding: "var(--space-8) var(--space-6)", paddingBottom: "100px" }}>
      <h1 style={{ fontSize: "1.25rem", fontWeight: 600, marginBottom: "var(--space-1)" }}>
        Inventory
      </h1>
      <p style={{
        fontSize: "0.875rem", color: "var(--color-text-muted)",
        marginBottom: "var(--space-8)",
      }}>
        Pantry and household supplies.
      </p>

      {loading && items.length === 0 ? (
        <p style={{ color: "var(--color-text-faint)", fontSize: "0.875rem" }}>Loading…</p>
      ) : items.length === 0 ? (
        <div style={{
          padding: "var(--space-6)", textAlign: "center",
          borderRadius: "var(--radius-lg)",
          border: "1px dashed var(--color-border)",
          color: "var(--color-text-faint)", fontSize: "0.875rem",
        }}>
          Inventory is empty. Add items from the worker.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-6)" }}>
          {categories.map((cat) => (
            <div key={cat}>
              <h2 style={{ fontSize: "0.75rem", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--color-text-faint)", marginBottom: "var(--space-3)", marginLeft: "2px", display: "flex", alignItems: "center", gap: "var(--space-2)" }}>
                {cat}
                <span style={{ fontWeight: 500, fontSize: "0.75rem", color: "var(--color-text-faint)" }}>
                  ({grouped[cat].length})
                </span>
              </h2>
              <div style={{
                background: "var(--color-surface)",
                borderRadius: "var(--radius-lg)",
                border: "1px solid var(--color-border)",
                overflow: "hidden"
              }}>
                {grouped[cat].map((item, idx) => {
                  const isEditing = editingId === item.id;
                  const isLast = idx === grouped[cat].length - 1;

                  let expiryColor = "var(--color-text-muted)";
                  let expiryPrefix = "Expires:";
                  if (item.expiry_date) {
                    const exp = new Date(item.expiry_date);
                    const today = new Date();
                    today.setHours(0, 0, 0, 0);
                    const diffDays = Math.ceil((exp.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));
                    if (diffDays < 0) {
                      expiryColor = "var(--color-danger)";
                      expiryPrefix = "Expired:";
                    } else if (diffDays <= 3) {
                      expiryColor = "var(--color-danger)";
                    }
                  }

                  const isLow = item.quantity <= 1;

                  return (
                    <div key={item.id} style={{
                      padding: "var(--space-4) var(--space-5)",
                      borderBottom: isLast ? "none" : "1px solid var(--color-border)",
                      display: "flex",
                      flexDirection: isEditing ? "column" : "row",
                      alignItems: isEditing ? "stretch" : "center",
                      justifyContent: "space-between",
                      cursor: "pointer",
                      background: isEditing ? "var(--color-surface-2)" : "transparent",
                      gap: isEditing ? "var(--space-3)" : "0",
                    }} onClick={() => setEditingId(isEditing ? null : item.id)}>
                      
                      {!isEditing && (
                        <div style={{ display: "flex", flexDirection: "column" }}>
                          <span style={{ fontSize: "0.9375rem", fontWeight: 500, color: "var(--color-text)" }}>
                            {item.item}
                          </span>
                          {item.expiry_date && (
                            <span style={{ fontSize: "0.75rem", color: expiryColor, marginTop: "2px" }}>
                              {expiryPrefix} {item.expiry_date}
                            </span>
                          )}
                        </div>
                      )}

                      {isEditing ? (
                        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }} onClick={(e) => e.stopPropagation()}>
                          <div style={{ display: "flex", flexDirection: "column" }}>
                            <span style={{ fontSize: "0.9375rem", fontWeight: 600, color: "var(--color-text)" }}>
                              {item.item}
                            </span>
                            <span style={{ fontSize: "0.75rem", color: "var(--color-text-faint)" }}>
                              Edit quantity
                            </span>
                          </div>
                          <div style={{ display: "flex", alignItems: "center", gap: "var(--space-3)", background: "var(--color-surface)", borderRadius: "var(--radius-md)", padding: "var(--space-1) var(--space-2)", border: "1px solid var(--color-border)", width: "fit-content" }}>
                            <button onClick={() => void updateQuantity(item.id, item.quantity - 1)} style={{ background: "transparent", border: "none", color: "var(--color-text)", fontSize: "1.125rem", cursor: "pointer", width: "24px", height: "24px", display: "flex", alignItems: "center", justifyContent: "center" }}>
                              −
                            </button>
                            <span style={{ fontSize: "0.9375rem", fontWeight: 600, minWidth: "20px", textAlign: "center", color: isLow ? "var(--color-warning, #c47a3b)" : "inherit" }}>
                              {item.quantity}
                            </span>
                            <button onClick={() => void updateQuantity(item.id, item.quantity + 1)} style={{ background: "transparent", border: "none", color: "var(--color-text)", fontSize: "1.125rem", cursor: "pointer", width: "24px", height: "24px", display: "flex", alignItems: "center", justifyContent: "center" }}>
                              +
                            </button>
                            <button onClick={() => setEditingId(null)} style={{ marginLeft: "var(--space-2)", background: "var(--color-primary-faint)", border: "none", borderRadius: "var(--radius-sm)", color: "var(--color-primary)", padding: "4px 8px", fontSize: "0.75rem", fontWeight: 600, cursor: "pointer" }}>
                              Done
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div style={{ fontSize: "0.9375rem", fontWeight: 600, color: isLow ? "var(--color-warning, #c47a3b)" : "var(--color-text-muted)", display: "flex", alignItems: "center", gap: "4px" }}>
                          {isLow && <span>⚠</span>}
                          {item.quantity} <span style={{ fontSize: "0.8125rem", fontWeight: 400 }}>{item.unit || ""}</span>
                        </div>
                      )}

                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
