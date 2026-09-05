#!/usr/bin/env bash
# Run the SQL test suites against a throwaway local Postgres.
#
# These test migration logic that is hard to verify by reading — the watchdog's
# alert/latch/recovery state machine, and the brain_directives constraints that
# back the executor's safety rules.
#
# Supabase-managed extensions (pg_cron, pg_net) are not installable locally, so
# _stubs.sql provides stand-ins with the real signatures and the CREATE
# EXTENSION lines are stripped from the watchdog migration before it runs.
#
#   ./supabase/tests/run.sh
#
# Requires a local postgres install (any recent version). Nothing here touches
# the real project.
set -euo pipefail

PGBIN="${PGBIN:-$(ls -d /usr/lib/postgresql/*/bin 2>/dev/null | sort -V | tail -1)}"
# Socket-only, so no port is needed.
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIGRATIONS="$DIR/../migrations"
WORK="$(mktemp -d)"

if [[ -z "$PGBIN" || ! -x "$PGBIN/initdb" ]]; then
  echo "Could not find a postgres install. Set PGBIN to its bin directory." >&2
  exit 1
fi

# initdb refuses to run as root, so drop to the postgres system user when we are.
RUN_AS=""
if [[ "$(id -u)" == "0" ]]; then
  RUN_AS="postgres"
  chown -R postgres:postgres "$WORK"
fi
run() { if [[ -n "$RUN_AS" ]]; then su "$RUN_AS" -c "$1"; else bash -c "$1"; fi; }

cleanup() {
  run "$PGBIN/pg_ctl -D $WORK/data stop -m immediate" >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT

echo "→ starting throwaway postgres in $WORK"
run "$PGBIN/initdb -D $WORK/data -U postgres --auth=trust" >/dev/null
# listen_addresses='' means unix socket only: no TCP port to collide with an
# already-running postgres, and nothing exposed off the machine.
run "$PGBIN/pg_ctl -D $WORK/data -o \"-c listen_addresses='' -k $WORK\" -l $WORK/pg.log -w start" >/dev/null

# The watchdog migration's CREATE EXTENSION lines cannot work locally.
grep -v '^CREATE EXTENSION' "$MIGRATIONS/20260828140000_heartbeat_watchdog.sql" \
  > "$WORK/watchdog.sql"
# The duration fix replaces check_worker_heartbeat and adds format_outage.
cp "$MIGRATIONS/20260831000000_fix_watchdog_duration.sql" "$WORK/watchdog_fix.sql"
cp "$MIGRATIONS/20260828150000_create_brain_directives.sql" "$WORK/brain.sql"
# travel_alerts and the migration that splits planning from delivery. Applied
# in order, so the ALTER is exercised against the shape it will actually meet.
cp "$MIGRATIONS/20260902120000_travel_alerts.sql"          "$WORK/travel.sql"
cp "$MIGRATIONS/20260902140000_travel_alert_planning.sql"  "$WORK/travel_planning.sql"
cp "$MIGRATIONS/20260903150000_nearby_services.sql"        "$WORK/nearby.sql"
cp "$MIGRATIONS/20260903200000_nearby_services_upsert_fix.sql" "$WORK/nearby_fix.sql"
# health_logs. The fix has to meet the shape phase 1 and phase 2 left behind —
# an expression index it must drop, a nullable meal_type it must rewrite, and
# duplicate rows that index was too weak to prevent. Replaying those two
# migrations directly is not possible here: phase 1 alters `inventory`, a table
# phase 3 has since dropped, so the file no longer runs against a current
# schema at all. seed_health_legacy.sql therefore carries that pre-fix DDL
# copied verbatim from both migrations, and the fix runs against it.
cp "$MIGRATIONS/20260603000001_create_user_profile.sql"     "$WORK/user_profile.sql"
cp "$MIGRATIONS/20260905140000_health_logs_upsert_key.sql"   "$WORK/health_fix.sql"
cp "$MIGRATIONS/20260606200000_create_agent_turns.sql"     "$WORK/agent_turns.sql"
cp "$MIGRATIONS/20260903180000_agent_turns_keep_traces.sql" "$WORK/agent_turns_retention.sql"
cp "$DIR"/_stubs.sql "$DIR"/test_watchdog.sql "$DIR"/test_brain_schema.sql \
   "$DIR"/test_travel_alerts.sql "$DIR"/test_nearby_services.sql \
   "$DIR"/test_function_grants.sql "$DIR"/test_agent_turns_retention.sql \
   "$DIR"/seed_health_legacy.sql "$DIR"/test_health_logs.sql "$WORK/"
chmod -R a+r "$WORK"

psql_run() {
  run "psql -h $WORK -U postgres -q -v ON_ERROR_STOP=1 -f $WORK/$1"
}

echo "→ applying stubs and migrations"
psql_run _stubs.sql  >/dev/null
psql_run watchdog.sql     >/dev/null
psql_run watchdog_fix.sql >/dev/null
psql_run brain.sql        >/dev/null
psql_run travel.sql          >/dev/null
psql_run travel_planning.sql >/dev/null
psql_run nearby.sql          >/dev/null
psql_run nearby_fix.sql      >/dev/null
psql_run agent_turns.sql            >/dev/null
psql_run agent_turns_retention.sql  >/dev/null

# health_logs, in the order production actually saw: the table and its
# expression index, then the rows that accumulated while that index was inert,
# and only then the fix. Seeding BEFORE the fix is the whole point — the merge
# and adoption steps are the part most likely to be wrong, and against an empty
# table they would pass without executing.
psql_run user_profile.sql       >/dev/null
psql_run seed_health_legacy.sql >/dev/null
psql_run health_fix.sql         >/dev/null

echo
echo "── watchdog ──────────────────────────────────────────"
psql_run test_watchdog.sql 2>&1 | grep -E "  ok |FAIL|passed|ERROR" | sed 's/^.*NOTICE: //'

echo
echo "── brain schema ──────────────────────────────────────"
psql_run test_brain_schema.sql 2>&1 | grep -E "  ok |FAIL|passed|ERROR" | sed 's/^.*NOTICE: //'

echo
echo "── travel alerts ─────────────────────────────────────"
psql_run test_travel_alerts.sql 2>&1 | grep -E "  ok |FAIL|passed|ERROR" | sed 's/^.*NOTICE: //'

echo
echo "── nearby services ───────────────────────────────────"
psql_run test_nearby_services.sql 2>&1 | grep -E "  ok |FAIL|passed|ERROR" | sed 's/^.*NOTICE: //'

echo
echo "── health logs ───────────────────────────────────────"
psql_run test_health_logs.sql 2>&1 | grep -E "  ok |FAIL|passed|ERROR" | sed 's/^.*NOTICE: //'

echo
echo "── function grants ───────────────────────────────────"
psql_run test_function_grants.sql 2>&1 | grep -E "  ok |FAIL|passed|ERROR" | sed 's/^.*NOTICE: //'

echo
echo "── trace retention ───────────────────────────────────"
psql_run test_agent_turns_retention.sql 2>&1 | grep -E "  ok |FAIL|passed|ERROR" | sed 's/^.*NOTICE: //'

echo
echo "✓ SQL suites passed"
