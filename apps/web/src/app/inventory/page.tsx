"use client";

export default function InventoryPage() {
  return (
    <div style={{ maxWidth: "800px", margin: "0 auto", padding: "var(--space-8) var(--space-5)" }}>
      <h1 style={{ fontSize: "1.125rem", fontWeight: 600, marginBottom: "var(--space-1)" }}>
        Inventory
      </h1>
      <p style={{
        fontSize: "0.8125rem", color: "var(--color-text-muted)",
        marginBottom: "var(--space-6)",
      }}>
        Groceries, pantry items, and household supplies.
      </p>
      <div style={{
        padding: "var(--space-8)", textAlign: "center",
        borderRadius: "var(--radius-lg)",
        border: "1px dashed var(--color-border)",
        color: "var(--color-text-faint)", fontSize: "0.8125rem",
      }}>
        Inventory tracking coming in Phase 2. Items with expiry dates, categories, and shopping list generation.
      </div>
    </div>
  );
}
