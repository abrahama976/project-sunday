"use server";

import { createClient } from "@/lib/supabase/server";
import { revalidatePath } from "next/cache";

export type ScheduledJob = {
  id: string;
  job_name: string;
  cron_expr: string;
  enabled: boolean;
  last_run_at: string | null;
};

export async function getScheduledJobs(): Promise<ScheduledJob[]> {
  const supabase = await createClient();
  const { data: userData } = await supabase.auth.getUser();
  if (!userData.user) return [];

  const { data, error } = await supabase
    .from("scheduled_jobs")
    .select("id, job_name, cron_expr, enabled, last_run_at")
    .order("job_name", { ascending: true });

  if (error || !data) return [];
  return data;
}

export async function toggleJobStatus(jobId: string, enabled: boolean): Promise<boolean> {
  const supabase = await createClient();
  const { data: userData } = await supabase.auth.getUser();
  if (!userData.user) return false;

  const { error } = await supabase
    .from("scheduled_jobs")
    .update({ enabled })
    .eq("id", jobId);

  if (error) {
    console.error("Error toggling job:", error);
    return false;
  }
  
  revalidatePath("/settings");
  return true;
}
