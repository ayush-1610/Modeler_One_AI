#!/usr/bin/env bash
# PostgreSQL for the single-node deployment: Keycloak's database, and the platform's database for the Part 11 records
# (audit trail and signatures; the schema is services/api/migrations). No sudo: PostgreSQL 16 from conda-forge (this
# server's ~/miniforge3) under ~/modeler-postgres, listening only on 127.0.0.1 and its own socket. Every password is
# random, kept in a file only this account can read, and handed over by environment or standard input; nobody types one.
#
#   postgres.sh install         PostgreSQL 16, the cluster, the roles and databases, the schema (safe to re-run)
#   postgres.sh migrate         apply the migrations not applied yet; each is recorded with its sha256 and never re-run
#   postgres.sh start | stop | status
#   postgres.sh backup          dump both databases into $MODELER_BACKUP_DIR/<date> (nightly from cron); keep 14 days
#   postgres.sh restore-check   restore the latest dumps into scratch databases and compare them with the live ones
#   postgres.sh env             the lines for ~/.modeler-secrets.env: Keycloak and the Part 11 records on PostgreSQL
#   postgres.sh verify          the Part 11 copy against the file audit chains (python -m modeler_api.part11)
#   postgres.sh applied         the server's version, then each applied migration and its sha256 (read by qualify.sh)
#
# Settings (environment, default in brackets): MODELER_POSTGRES_HOME [~/modeler-postgres], MODELER_POSTGRES_PORT
# [5432], MODELER_BACKUP_DIR [~/modeler-backups] (better on another disk), MODELER_POSTGRES_BIN (an existing
# PostgreSQL 16 bin directory to use instead of installing one).
#
# Roles: `modeler_owner` owns the platform's schema and only runs migrations (no login); `modeler` is the API's login,
# without UPDATE, DELETE or TRUNCATE on the append-only Part 11 tables (their triggers refuse those too); `keycloak`
# owns Keycloak's database. The superuser `postgres` is used by this script only.
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/_env.sh"

PG_ROOT="${MODELER_POSTGRES_HOME:-$HOME/modeler-postgres}"
PG_DATA="$PG_ROOT/data"
PG_RUN="$PG_ROOT/run"
PG_SECRETS="$PG_ROOT/secrets"
PG_PORT="${MODELER_POSTGRES_PORT:-5432}"
BACKUPS="${MODELER_BACKUP_DIR:-$HOME/modeler-backups}"
MIGRATIONS="$REPO/services/api/migrations"
KEEP_DAYS=14

die() { echo "postgres.sh: $*" >&2; exit 1; }

# The PostgreSQL 16 binaries: MODELER_POSTGRES_BIN, else the conda-forge install under PG_ROOT.
pg_bin() {
  if [ -n "${MODELER_POSTGRES_BIN:-}" ]; then echo "$MODELER_POSTGRES_BIN"; return; fi
  [ -x "$PG_ROOT/env/bin/pg_ctl" ] && { echo "$PG_ROOT/env/bin"; return; }
  return 1
}

secret() { cat "$PG_SECRETS/$1.pass"; }
new_secret() { [ -f "$PG_SECRETS/$1.pass" ] || ( umask 077; head -c 32 /dev/urandom | base64 | tr -d '/+=\n' > "$PG_SECRETS/$1.pass" ); }
installed() { [ -f "$PG_DATA/PG_VERSION" ]; }
running() { installed && "$BIN/pg_ctl" -D "$PG_DATA" status >/dev/null 2>&1; }
# psql as the superuser, over TCP on 127.0.0.1; the password by environment, SQL on standard input
sql() {
  PGPASSWORD="$(secret postgres)" PGOPTIONS="-c client_min_messages=warning" \
    "$BIN/psql" -X -q -At -v ON_ERROR_STOP=1 -h 127.0.0.1 -p "$PG_PORT" -U postgres "$@"
}

cmd_start() {
  installed || die "not installed: run 'postgres.sh install'"
  if running; then echo "postgres already running (127.0.0.1:$PG_PORT)"; return; fi
  "$BIN/pg_ctl" -D "$PG_DATA" -l "$LOGS/postgres.log" -w -t 60 start >/dev/null || die "did not start; see $LOGS/postgres.log"
  echo "postgres up (127.0.0.1:$PG_PORT)"
}

cmd_stop() {
  if running; then "$BIN/pg_ctl" -D "$PG_DATA" -m fast -w stop >/dev/null; echo "postgres stopped"; else echo "postgres not running"; fi
}

cmd_status() {
  if running && "$BIN/pg_isready" -q -h 127.0.0.1 -p "$PG_PORT"; then
    echo "postgres UP    127.0.0.1:$PG_PORT   databases keycloak, modeler   (log $LOGS/postgres.log)"
  else
    echo "postgres DOWN  (start: bash deploy/server/postgres.sh start)"; return 1
  fi
}

cmd_install() {
  mkdir -p "$PG_ROOT" "$PG_RUN" "$PG_SECRETS" && chmod 700 "$PG_RUN" "$PG_SECRETS"
  if ! BIN="$(pg_bin)"; then
    command -v conda >/dev/null || die "no PostgreSQL and no conda to install it (expected ~/miniforge3)"
    echo "installing PostgreSQL 16 from conda-forge into $PG_ROOT/env"
    conda create -y -q -p "$PG_ROOT/env" -c conda-forge "postgresql=16" >/dev/null
    BIN="$PG_ROOT/env/bin"
  fi
  "$BIN/postgres" --version | grep -q ' 16\.' || die "$BIN is not PostgreSQL 16"
  for role in postgres keycloak modeler; do new_secret "$role"; done
  if ! installed; then
    "$BIN/initdb" -D "$PG_DATA" -U postgres --pwfile="$PG_SECRETS/postgres.pass" --auth=scram-sha-256 \
      --encoding=UTF8 --locale=C >/dev/null
    cat >> "$PG_DATA/postgresql.conf" <<EOF

# Modeler One (deploy/server/postgres.sh): reachable from this machine only
listen_addresses = '127.0.0.1'
port = $PG_PORT
unix_socket_directories = '$PG_RUN'
password_encryption = scram-sha-256
EOF
  fi
  cmd_start
  # roles and databases, created once; the passwords are set from the secret files on every install
  sql -d postgres <<'SQL'
SELECT 'CREATE ROLE modeler_owner NOLOGIN' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'modeler_owner') \gexec
SELECT 'CREATE ROLE modeler LOGIN' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'modeler') \gexec
SELECT 'CREATE ROLE keycloak LOGIN' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'keycloak') \gexec
SELECT 'CREATE DATABASE modeler OWNER modeler_owner' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'modeler') \gexec
SELECT 'CREATE DATABASE keycloak OWNER keycloak' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'keycloak') \gexec
REVOKE ALL ON DATABASE modeler FROM PUBLIC;
REVOKE ALL ON DATABASE keycloak FROM PUBLIC;
GRANT CONNECT ON DATABASE modeler TO modeler;
SQL
  printf "ALTER ROLE modeler PASSWORD '%s';\nALTER ROLE keycloak PASSWORD '%s';\n" "$(secret modeler)" "$(secret keycloak)" \
    | sql -d postgres
  cmd_migrate
  echo "installed. Keycloak on PostgreSQL: see deploy/keycloak/README.md ('keycloak.sh migrate-db')"
}

# Each migration runs once, in its own transaction, as modeler_owner; its sha256 is recorded, and a migration that
# changed after it was applied stops everything (migrations are locked files: a new change is a new file).
cmd_migrate() {
  running || die "not running: run 'postgres.sh start'"
  sql -d modeler <<'SQL'
SET ROLE modeler_owner;
CREATE TABLE IF NOT EXISTS schema_migrations (
  name text PRIMARY KEY, sha256 text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now());
SQL
  local file name sum recorded
  for file in "$MIGRATIONS"/*.sql; do
    name="$(basename "$file")"
    sum="$(sha256sum "$file" | cut -d' ' -f1)"
    recorded="$(sql -d modeler -c "SELECT sha256 FROM schema_migrations WHERE name = '$name'")"
    if [ -n "$recorded" ]; then
      [ "$recorded" = "$sum" ] || die "$name changed after it was applied (recorded $recorded, now $sum)"
      continue
    fi
    { echo "SET ROLE modeler_owner;"; echo "BEGIN;"; cat "$file"; echo
      echo "INSERT INTO schema_migrations (name, sha256) VALUES ('$name', '$sum');"; echo "COMMIT;"; } | sql -d modeler
    echo "applied $name"
  done
  # the API's login: read and write, except changing or removing what the append-only triggers protect
  sql -d modeler <<'SQL'
SET ROLE modeler_owner;
GRANT USAGE ON SCHEMA public TO modeler;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO modeler;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO modeler;
REVOKE INSERT, UPDATE, DELETE ON schema_migrations FROM modeler;
SELECT format('REVOKE UPDATE, DELETE, TRUNCATE ON %I FROM modeler', c.relname)
  FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid JOIN pg_proc p ON p.oid = t.tgfoid
  WHERE p.proname = 'reject_mutation' GROUP BY c.relname \gexec
SQL
}

cmd_backup() {
  if ! installed; then echo "postgres not installed: nothing to back up"; return; fi
  running || die "not running: a backup needs the server up"
  local dir; dir="$BACKUPS/$(date -u +%F)"
  ( umask 077; mkdir -p "$dir" )
  for db in keycloak modeler; do   # the dumps hold password hashes and authenticator secrets: this account only
    ( umask 077; PGPASSWORD="$(secret postgres)" "$BIN/pg_dump" -h 127.0.0.1 -p "$PG_PORT" -U postgres -Fc \
        -f "$dir/$db.dump" "$db" )
  done
  # dated folders only, never anything else in the folder
  find "$BACKUPS" -mindepth 1 -maxdepth 1 -type d -name '20[0-9][0-9]-[0-9][0-9]-[0-9][0-9]' -mtime +"$KEEP_DAYS" \
    -exec rm -rf {} +
  echo "backup: $dir (keycloak.dump, modeler.dump; folders older than $KEEP_DAYS days removed)"
}

# Restore the latest dumps into scratch databases, check every table came back with no more rows than the live one
# holds (the live one may have grown since), then drop the scratch databases.
cmd_restore_check() {
  running || die "not running"
  local dir; dir="$(find "$BACKUPS" -mindepth 1 -maxdepth 1 -type d -name '20*' | sort | tail -1)"
  [ -n "$dir" ] || die "no backup in $BACKUPS"
  local db scratch problems=0 table live restored
  for db in keycloak modeler; do
    scratch="restore_check_$db"
    sql -d postgres -c "DROP DATABASE IF EXISTS $scratch" -c "CREATE DATABASE $scratch"
    PGPASSWORD="$(secret postgres)" "$BIN/pg_restore" -h 127.0.0.1 -p "$PG_PORT" -U postgres --no-owner \
      -d "$scratch" "$dir/$db.dump" || problems=$((problems + 1))
    while read -r table; do
      live="$(sql -d "$db" -c "SELECT count(*) FROM public.\"$table\"")"
      restored="$(sql -d "$scratch" -c "SELECT count(*) FROM public.\"$table\"" 2>/dev/null || echo missing)"
      if [ "$restored" = missing ] || [ "$restored" -gt "$live" ]; then
        echo "  $db.$table: live $live, restored $restored"; problems=$((problems + 1))
      fi
    done < <(sql -d "$db" -c "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1")
    sql -d postgres -c "DROP DATABASE $scratch"
  done
  [ "$problems" = 0 ] || die "restore check of $dir found $problems problem(s)"
  echo "restore check: $dir restores completely (keycloak, modeler)"
}

cmd_env() {
  installed || die "not installed: run 'postgres.sh install'"
  cat <<EOF
# PostgreSQL (deploy/server/postgres.sh env): add to ~/.modeler-secrets.env (mode 600), then restart the stack.
export MODELER_KEYCLOAK_DB=postgres
export MODELER_PART11_STORE=postgres
export MODELER_DATABASE_URL=postgresql+asyncpg://modeler:$(secret modeler)@127.0.0.1:$PG_PORT/modeler
EOF
}

# The Part 11 copy against the file chains; the database URL goes by environment (never in the process list).
cmd_verify() {
  if [ "${MODELER_PART11_STORE:-file}" != postgres ]; then echo "Part 11 records are kept in files only: nothing to verify"; return; fi
  cd "$REPO" && uv run --quiet python -m modeler_api.part11 verify
}

# For the Installation Qualification (deploy/server/qualify.py): the server version, then "name sha256" per migration.
cmd_applied() {
  running || die "not running: run 'postgres.sh start'"
  sql -d modeler -c "SHOW server_version"
  sql -d modeler -c "SELECT name || ' ' || sha256 FROM schema_migrations ORDER BY name"
}

BIN="$(pg_bin || true)"
case "${1:-}" in
  install) cmd_install ;;
  migrate) [ -n "$BIN" ] || die "not installed"; cmd_migrate ;;
  start) [ -n "$BIN" ] || die "not installed: run 'postgres.sh install'"; cmd_start ;;
  stop) [ -n "$BIN" ] || { echo "postgres not installed"; exit 0; }; cmd_stop ;;
  status) [ -n "$BIN" ] || { echo "postgres not installed"; exit 1; }; cmd_status ;;
  backup) [ -n "$BIN" ] || { echo "postgres not installed: nothing to back up"; exit 0; }; cmd_backup ;;
  env) [ -n "$BIN" ] || die "not installed"; cmd_env ;;
  verify) cmd_verify ;;
  applied) [ -n "$BIN" ] || die "not installed"; cmd_applied ;;
  restore-check) [ -n "$BIN" ] || { echo "postgres not installed: nothing to check"; exit 0; }; cmd_restore_check ;;
  *) sed -n '2,20p' "$0"; exit 2 ;;
esac
