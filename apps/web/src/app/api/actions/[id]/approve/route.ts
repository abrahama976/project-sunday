import { NextRequest, NextResponse } from "next/server";
import { createClient, createServiceRoleClient } from "@/lib/supabase/server";

export async function POST(
  _request: NextRequest,
  ctx: { params: Promise<{ id: string }> }
) {
  const { id } = await ctx.params;

  // 1. Verify the caller is authenticated.
  const supabase = await createClient();
  const { data: { user }, error: authErr } = await supabase.auth.getUser();
  if (authErr || !user) {
    return NextResponse.json({ error: "unauthorized" }, { status: 401 });
  }

  // 2. Use the service-role client to UPDATE — guarded by our auth check above.
  const admin = createServiceRoleClient();

  // 3. Only allow approving rows currently in 'awaiting_approval'. Prevents replay/upgrade.
  const { data, error } = await admin
    .from("action_queue")
    .update({
      approved: true,
      status: "approved",
      approved_at: new Date().toISOString(),
      approved_by: user.id,
    })
    .eq("id", id)
    .eq("status", "awaiting_approval")
    .select()
    .single();

  if (error) {
    return NextResponse.json({ error: error.message }, { status: 400 });
  }
  if (!data) {
    return NextResponse.json({ error: "row not pending" }, { status: 409 });
  }

  return NextResponse.json({ ok: true, action: data });
}