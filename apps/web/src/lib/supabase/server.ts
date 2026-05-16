import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

/**
 * Standard server client (uses ANON key + user session cookies).
 * Use this for read paths where RLS should enforce per-user access.
 */
export async function createClient() {
  const cookieStore = await cookies();
  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet) {
          try {
            cookiesToSet.forEach(({ name, value, options }) =>
              cookieStore.set(name, value, options)
            );
          } catch {
            // Server Component context — cookies are read-only here.
            // Middleware handles refresh, so this is safe to ignore.
          }
        },
      },
    }
  );
}

/**
 * Service-role client. BYPASSES RLS. Use ONLY in Route Handlers /
 * Server Actions AFTER you have verified auth.uid() yourself.
 * Never expose this client to a browser context.
 */
import { createClient as createServiceClient } from "@supabase/supabase-js";

export function createServiceRoleClient() {
  return createServiceClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.SUPABASE_SERVICE_ROLE_KEY!,
    { auth: { persistSession: false, autoRefreshToken: false } }
  );
}