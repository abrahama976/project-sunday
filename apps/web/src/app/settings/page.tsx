import { getScheduledJobs } from "./actions";
import JobManager from "./job_manager";

export const dynamic = 'force-dynamic';

export default async function SettingsPage() {
  const jobs = await getScheduledJobs();

  return (
    <div style={{ maxWidth: "800px", margin: "0 auto", padding: "var(--space-8) var(--space-6)" }}>
      <h1 style={{ fontSize: "1.125rem", fontWeight: 600, marginBottom: "var(--space-1)" }}>
        Settings
      </h1>
      <p style={{ fontSize: "0.8125rem", color: "var(--color-text-muted)", marginBottom: "var(--space-6)" }}>
        Manage background tasks and worker schedules.
      </p>
      
      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-3)" }}>
        {jobs.length === 0 ? (
          <div style={{ padding: "var(--space-4)", textAlign: "center", color: "var(--color-text-muted)", fontSize: "0.875rem", border: "1px solid var(--color-border)", borderRadius: "var(--radius-lg)" }}>
            No scheduled jobs found.
          </div>
        ) : (
          jobs.map(job => (
            <JobManager key={job.id} job={job} />
          ))
        )}
      </div>
    </div>
  );
}
