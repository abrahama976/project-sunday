"use client";

import { useTransition } from "react";
import { ScheduledJob, toggleJobStatus } from "./actions";

function formatJobName(name: string) {
  return name.split("_").map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(" ");
}

function timeAgo(dateString: string | null) {
  if (!dateString) return "Never run";
  const diff = Date.now() - new Date(dateString).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return "Just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export default function JobManager({ job }: { job: ScheduledJob }) {
  const [isPending, startTransition] = useTransition();

  const handleToggle = () => {
    const newStatus = !job.enabled;
    startTransition(async () => {
      await toggleJobStatus(job.id, newStatus);
    });
  };

  return (
    <div style={{
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      padding: "var(--space-4) var(--space-5)",
      background: "var(--color-surface)",
      border: "1px solid var(--color-border)",
      borderRadius: "var(--radius-lg)",
      opacity: isPending ? 0.7 : 1,
      transition: "opacity 200ms ease"
    }}>
      <div>
        <div style={{ fontSize: "0.9375rem", fontWeight: 500, color: "var(--color-text)" }}>
          {formatJobName(job.job_name)}
        </div>
        <div style={{ fontSize: "0.75rem", color: "var(--color-text-muted)", marginTop: "4px", display: "flex", gap: "12px", alignItems: "center" }}>
          <span>{job.cron_expr}</span>
          <span>•</span>
          <span>Last: {timeAgo(job.last_run_at)}</span>
        </div>
      </div>
      
      <button 
        onClick={handleToggle}
        disabled={isPending}
        style={{
          width: "44px",
          height: "24px",
          borderRadius: "999px",
          border: "none",
          padding: "2px",
          cursor: isPending ? "wait" : "pointer",
          background: job.enabled ? "var(--color-brand)" : "var(--color-surface-hover)",
          transition: "background 200ms ease",
          position: "relative",
          display: "flex",
          alignItems: "center",
          flexShrink: 0
        }}
        aria-pressed={job.enabled}
        aria-label={`Toggle ${job.job_name}`}
      >
        <div style={{
          width: "20px",
          height: "20px",
          borderRadius: "50%",
          background: "#ffffff",
          boxShadow: "0 1px 2px rgba(0,0,0,0.15)",
          transform: job.enabled ? "translateX(20px)" : "translateX(0)",
          transition: "transform 200ms cubic-bezier(0.175, 0.885, 0.32, 1.275)"
        }} />
      </button>
    </div>
  );
}
