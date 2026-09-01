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
cp "$DIR"/_stubs.sql "$DIR"/test_watchdog.sql "$DIR"/test_brain_schema.sql "$WORK/"
chmod -R a+r "$WORK"

psql_run() {
  run "psql -h $WORK -U postgres -q -v ON_ERROR_STOP=1 -f $WORK/$1"
}

echo "→ applying stubs and migrations"
psql_run _stubs.sql  >/dev/null
psql_run watchdog.sql     >/dev/null
psql_run watchdog_fix.sql >/dev/null
psql_run brain.sql        >/dev/null

echo
echo "── watchdog ──────────────────────────────────────────"
psql_run test_watchdog.sql 2>&1 | grep -E "  ok |FAIL|passed" | sed 's/^.*NOTICE: //'

echo
echo "── brain schema ──────────────────────────────────────"
psql_run test_brain_schema.sql 2>&1 | grep -E "  ok |FAIL|passed" | sed 's/^.*NOTICE: //'

echo
echo "✓ SQL suites passed"
