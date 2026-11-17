import { NextRequest, NextResponse } from "next/server";
import { createClient, createServiceRoleClient } from "@/lib/supabase/server";

export async function POST(
  _request: NextRequest,
  ctx: { params: Promise<{ id: string }> }
) {
  const { id } = await ctx.params;

  const supabase = await createClient();
  const { data: { user }, error: authErr } = await supabase.auth.getUser();
  if (authErr || !user) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  // Service-role client: it bypasses RLS, so the ownership predicate below is
  // the enforcement boundary on this path, not a defence in depth.
  const admin = createServiceRoleClient();
  const { data, error } = await admin
    .from("action_queue")
    .update({
      approved: false,
      status: "denied",
      approved_at: new Date().toISOString(),
      approved_by: user.id,
    })
    .eq("id", id)
    .eq("user_id", user.id)
    .eq("status", "awaiting_approval")
    .select()
    .single();

  // 404 for absent, foreign-owned and already-resolved ids alike.
  if (error || !data) {
    return NextResponse.json({ error: "Not found" }, { status: 404 });
  }

  return NextResponse.json({ ok: true, action: data });
}