#!/usr/bin/env bash
#
# db-setup.sh — initialise the Postgres+pgvector database for the Docker stack.
#
#   ./scripts/db-setup.sh fresh                 # apply schema + seed data (new install)
#   ./scripts/db-setup.sh restore <dump.sql.gz> # load a pg_dump (e.g. a backup)
#   ./scripts/db-setup.sh psql                  # open a psql shell in the db container
#
# Run AFTER `docker compose up -d db` and BEFORE starting the api.
#
set -euo pipefail
cd "$(dirname "$0")/.."

[ -f .env ] || { echo "No .env found. Run: cp .env.example .env"; exit 1; }
set -a; . ./.env; set +a
PGUSER="${PGUSER:-sense}"; PGDATABASE="${PGDATABASE:-sense}"

dc() { docker compose "$@"; }
psql_in() { dc exec -T db psql -v ON_ERROR_STOP=1 -U "$PGUSER" -d "$PGDATABASE" "$@"; }

# Ensure the db container is up and accepting connections.
dc ps db >/dev/null 2>&1 || { echo "Start the database first: docker compose up -d db"; exit 1; }
echo "Waiting for the database to be ready..."
until dc exec -T db pg_isready -U "$PGUSER" -d "$PGDATABASE" >/dev/null 2>&1; do sleep 1; done

case "${1:-help}" in
  fresh)
    echo "Applying schema + seed data (db/schema.sql)..."
    psql_in < db/schema.sql
    echo "Done. Schema, device types, knowledge base, and AQI breakpoints loaded."
    ;;

  restore)
    FILE="${2:-}"
    [ -n "$FILE" ] && [ -f "$FILE" ] || { echo "Usage: $0 restore <dump.sql[.gz]>"; exit 1; }
    echo "Restoring $FILE into '$PGDATABASE' ..."
    case "$FILE" in
      *.gz) gunzip -c "$FILE" | psql_in ;;
      *)    psql_in < "$FILE" ;;
    esac
    echo "Restore complete. Row counts:"
    psql_in -c "SELECT relname, n_live_tup FROM pg_stat_user_tables ORDER BY n_live_tup DESC;"
    ;;

  psql)
    dc exec db psql -U "$PGUSER" -d "$PGDATABASE"
    ;;

  *)
    echo "Usage: $0 {fresh | restore <dump.sql[.gz]> | psql}"
    ;;
esac
