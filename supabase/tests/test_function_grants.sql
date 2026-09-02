-- No SECURITY DEFINER function in `public` may be executable by anon or PUBLIC.
--
-- This exists because get_active_users was exactly that: definer-rights, so it
-- ignored RLS, and granted to PUBLIC and anon — and the anon key ships inside
-- the web bundle. Anyone who opened the app could read email addresses out of
-- auth.users. It was found by an audit, months after it shipped. The next one
-- should be found here instead.

CREATE OR REPLACE FUNCTION assert(label text, cond boolean) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    IF cond THEN RAISE NOTICE '  ok  %', label;
    ELSE RAISE EXCEPTION 'FAIL: %', label;
    END IF;
END;
$$;

-- A definer-rights function is reachable by the public if it grants EXECUTE to
-- anon, to PUBLIC explicitly, or carries NO acl at all — because the default
-- for a function is PUBLIC EXECUTE. That last case is the quiet one: a
-- migration that only says CREATE FUNCTION ... SECURITY DEFINER is already
-- open to everyone without a single GRANT in sight.
CREATE OR REPLACE FUNCTION public_definer_functions()
RETURNS TABLE(fname text)
LANGUAGE sql AS $$
    SELECT p.proname::text
      FROM pg_proc p
      JOIN pg_namespace n ON n.oid = p.pronamespace
     WHERE n.nspname = 'public'
       AND p.prosecdef
       AND p.proname NOT IN ('public_definer_functions', 'assert')
       AND (
            p.proacl IS NULL
         OR EXISTS (
              SELECT 1 FROM aclexplode(p.proacl) a
               WHERE a.privilege_type = 'EXECUTE'
                 AND (a.grantee = 0                                  -- PUBLIC
                      OR pg_get_userbyid(a.grantee) = 'anon')
            )
       );
$$;

SELECT assert('no SECURITY DEFINER function is reachable by anon or PUBLIC',
    (SELECT count(*) = 0 FROM public_definer_functions()));

-- The guard is only worth having if it actually fires, so prove it does rather
-- than trusting a query that returns zero rows.
CREATE FUNCTION public.deliberately_insecure() RETURNS int
LANGUAGE sql SECURITY DEFINER AS $$ SELECT 1 $$;
GRANT EXECUTE ON FUNCTION public.deliberately_insecure() TO anon;

SELECT assert('...and the check catches one that is',
    (SELECT count(*) = 1 FROM public_definer_functions()
      WHERE fname = 'deliberately_insecure'));

REVOKE EXECUTE ON FUNCTION public.deliberately_insecure() FROM anon, PUBLIC;
SELECT assert('...and stops flagging it once the grant is revoked',
    (SELECT count(*) = 0 FROM public_definer_functions()
      WHERE fname = 'deliberately_insecure'));

DROP FUNCTION public.deliberately_insecure();

-- The no-ACL case, which is open by default with no GRANT written anywhere.
CREATE FUNCTION public.definer_no_grants() RETURNS int
LANGUAGE sql SECURITY DEFINER AS $$ SELECT 1 $$;
SELECT assert('a definer function with no explicit grants is caught too',
    (SELECT count(*) = 1 FROM public_definer_functions()
      WHERE fname = 'definer_no_grants'));
DROP FUNCTION public.definer_no_grants();

-- A function without definer rights runs as the caller and obeys RLS, so a
-- public grant on one is not the same problem.
CREATE FUNCTION public.ordinary_invoker() RETURNS int
LANGUAGE sql AS $$ SELECT 1 $$;
SELECT assert('an ordinary invoker-rights function is not flagged',
    (SELECT count(*) = 0 FROM public_definer_functions()
      WHERE fname = 'ordinary_invoker'));
DROP FUNCTION public.ordinary_invoker();

DO $$ BEGIN RAISE NOTICE ' ✓ all function-grant tests passed'; END $$;
