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
