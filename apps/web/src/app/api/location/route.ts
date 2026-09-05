import { NextRequest, NextResponse } from "next/server";
import { createClient, createServiceRoleClient } from "@/lib/supabase/server";

/**
 * POST /api/location — where the phone currently is.
 *
 * Accepts `{ lat, lng, timezone }` from two callers, which is why there are
 * two ways in:
 *
 *   - **A signed-in browser.** The Travel page asks for a fix and posts it, so
 *     "start from where I am" means something. Authenticated by the session
 *     cookie, like every other page-driven write in this app.
 *   - **A phone automation** (Tasker, Shortcuts) with no session to offer.
 *     Authenticated by `x-sunday-secret`.
 *
 *   curl -X POST https://your-app.vercel.app/api/location \
 *     -H "Content-Type: application/json" \
 *     -H "x-sunday-secret: YOUR_SECRET" \
 *     -d '{"lat": -33.8688, "lng": 151.2093, "timezone": "Australia/Sydney"}'
 *
 * The row is keyed on `user_id`, and writing it is not optional: the worker's
 * `resolve_origin` reads `.eq("user_id", …)`, so a fix stored without one is a
 * fix the worker cannot see. This route previously wrote none and upserted on
 * `id` — whose default is a fresh uuid, so it never conflicted and simply
 * inserted. Both faults were silent, and between them the live-location branch
 * had never once run.
 */
export async function POST(request: NextRequest) {
  const secret = request.headers.get("x-sunday-secret");
  const expectedSecret = process.env.SUNDAY_LOCATION_SECRET;
  const bySecret = Boolean(expectedSecret) && secret === expectedSecret;

  // The session is only consulted when the shared secret was not presented, so
  // an automation posting the right secret costs no round trip to auth.
  let userId: string | null = null;
  if (!bySecret) {
    const supabase = await createClient();
    const { data: { user } } = await supabase.auth.getUser();
    if (!user) {
      return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
    }
    userId = user.id;
  }

  let body: { lat?: number; lng?: number; timezone?: string };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
  }

  const { lat, lng, timezone } = body;

  if (typeof lat !== "number" || typeof lng !== "number") {
    return NextResponse.json(
      { error: "lat and lng are required as numbers" },
      { status: 400 }
    );
  }

  if (lat < -90 || lat > 90 || lng < -180 || lng > 180) {
    return NextResponse.json(
      { error: "lat must be [-90, 90], lng must be [-180, 180]" },
      { status: 400 }
    );
  }

  const admin = createServiceRoleClient();

  // An automation authenticates as the installation rather than as a person,
  // so it has no user to name. This is a one-user system — utils.resolve_user
  // raises if a second ever appears — so the single profile is the answer, and
  // saying so beats writing a NULL the worker would silently ignore.
  if (!userId) {
    const { data: profile, error: profileErr } = await admin
      .from("user_profile")
      .select("user_id")
      .limit(1)
      .maybeSingle();
    if (profileErr || !profile?.user_id) {
      return NextResponse.json(
        { error: "No user to attach this location to" },
        { status: 409 }
      );
    }
    userId = profile.user_id;
  }

  const { error } = await admin
    .from("user_location")
    .upsert(
      {
        user_id: userId,
        lat,
        lng,
        timezone: timezone || "Australia/Sydney",
        updated_at: new Date().toISOString(),
      },
      { onConflict: "user_id" }
    );

  if (error) {
    console.error("[api/location] upsert error:", error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({
    ok: true,
    lat,
    lng,
    timezone: timezone || "Australia/Sydney",
  });
}
