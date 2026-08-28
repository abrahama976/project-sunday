"use server";

import { createClient } from "@/lib/supabase/server";
import { revalidatePath } from "next/cache";

export async function getProfileContent(): Promise<string> {
  const supabase = await createClient();
  const { data: userData } = await supabase.auth.getUser();
  if (!userData.user) return "";

  const { data, error } = await supabase
    .from("user_profile")
    .select("content")
    .eq("user_id", userData.user.id)
    .maybeSingle();

  if (error || !data) return "";
  return data.content;
}

export type Directive = {
  id: string;
  directive: string;
  scope: string;
  source: string;
  weight: number;
  created_at: string;
};

/** Active learned directives, strongest first — the same order the worker
 *  renders them into the system prompt. */
export async function getDirectives(): Promise<Directive[]> {
  const supabase = await createClient();
  const { data: userData } = await supabase.auth.getUser();
  if (!userData.user) return [];

  const { data, error } = await supabase
    .from("brain_directives")
    .select("id, directive, scope, source, weight, created_at")
    .eq("user_id", userData.user.id)
    .eq("active", true)
    .order("weight", { ascending: false })
    .order("created_at", { ascending: true });

  if (error || !data) return [];
  return data as Directive[];
}

/** Retire a directive. Soft-delete: the row stays for audit, matching the
 *  project's no-hard-deletes rule. The worker picks the change up within 10s
 *  via its brain poll. */
export async function retireDirective(id: string): Promise<{ success: boolean; error?: string }> {
  const supabase = await createClient();
  const { data: userData } = await supabase.auth.getUser();
  if (!userData.user) return { success: false, error: "Not authenticated" };

  const { error } = await supabase
    .from("brain_directives")
    .update({ active: false })
    .eq("id", id)
    .eq("user_id", userData.user.id);

  if (error) return { success: false, error: error.message };

  revalidatePath("/profile");
  return { success: true };
}

export async function saveProfileContent(content: string): Promise<{ success: boolean; error?: string }> {
  const supabase = await createClient();
  const { data: userData } = await supabase.auth.getUser();
  if (!userData.user) return { success: false, error: "Not authenticated" };

  const { error } = await supabase
    .from("user_profile")
    .upsert({ 
      user_id: userData.user.id, 
      content 
    }, { onConflict: "user_id" });

  if (error) {
    return { success: false, error: error.message };
  }
  
  revalidatePath("/profile");
  return { success: true };
}
