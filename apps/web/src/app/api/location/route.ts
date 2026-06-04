import { NextRequest, NextResponse } from "next/server";
import { createServiceRoleClient } from "@/lib/supabase/server";

/**
 * POST /api/location
 *
 * Accepts { lat, lng, timezone } and upserts into user_location.
 * Authenticated via x-sunday-secret header (for Android Tasker / Shortcuts).
 *
 * Example curl:
 *   curl -X POST https://your-app.vercel.app/api/location \
 *     -H "Content-Type: application/json" \
 *     -H "x-sunday-secret: YOUR_SECRET" \
 *     -d '{"lat": -33.8688, "lng": 151.2093, "timezone": "Australia/Sydney"}'
 */
export async function POST(request: NextRequest) {
  const secret = request.headers.get("x-sunday-secret");
  const expectedSecret = process.env.SUNDAY_LOCATION_SECRET;

  if (!expectedSecret || secret !== expectedSecret) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
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

  const tz = timezone || "Australia/Sydney";

  const supabase = createServiceRoleClient();

  // Upsert — single-row table, keyed on the fixed id
  const { error } = await supabase
    .from("user_location")
    .upsert(
      { lat, lng, timezone: tz, updated_at: new Date().toISOString() },
      { onConflict: "id" }
    );

  if (error) {
    console.error("[api/location] upsert error:", error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({ ok: true, lat, lng, timezone: tz });
}
