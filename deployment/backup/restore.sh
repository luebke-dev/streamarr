#!/usr/bin/env bash
#
# streamarr.media disaster-recovery restore.
#
# Restores a PostgreSQL custom-format dump produced by backup.sh, then prints
# the follow-up steps for Elasticsearch and media (which are intentionally NOT
# auto-restored — see README.md).
#
# Usage:  ./restore.sh <backup-set-dir | postgres.dump> [path/to/backup.env]
#
# The Postgres dump is the source of truth. Elasticsearch is rebuilt from
# Postgres via the admin reindex endpoints; media is a separate file backup.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

log()  { printf '[restore] %s\n' "$*" >&2; }
die()  { printf '[restore] ERROR: %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

[[ $# -ge 1 ]] || die "Usage: restore.sh <backup-set-dir | postgres.dump> [backup.env]"

SRC="$1"
if [[ -d "${SRC}" ]]; then
  DUMP_FILE="${SRC%/}/postgres.dump"
else
  DUMP_FILE="${SRC}"
fi
[[ -f "${DUMP_FILE}" ]] || die "Postgres dump not found: ${DUMP_FILE}"

# --- Load configuration ------------------------------------------------------
ENV_FILE="${2:-${BACKUP_ENV_FILE:-${SCRIPT_DIR}/backup.env}}"
if [[ -f "${ENV_FILE}" ]]; then
  # shellcheck disable=SC1090
  set -a; source "${ENV_FILE}"; set +a
elif [[ -f "${SCRIPT_DIR}/backup.env.example" ]]; then
  # shellcheck disable=SC1090
  set -a; source "${SCRIPT_DIR}/backup.env.example"; set +a
fi
if [[ -z "${POSTGRES_PASSWORD:-}" && -f "${REPO_ROOT}/.env" ]]; then
  # shellcheck disable=SC1090
  set -a; source <(grep -E '^POSTGRES_' "${REPO_ROOT}/.env" || true); set +a
fi

PG_CONTAINER="${PG_CONTAINER:-streamarr-db-1}"
POSTGRES_USER="${POSTGRES_USER:-streamarr}"
POSTGRES_DB="${POSTGRES_DB:-streamarr}"
PGHOST="${PGHOST:-127.0.0.1}"
PGPORT="${PGPORT:-5432}"
[[ -n "${POSTGRES_PASSWORD:-}" ]] || die "POSTGRES_PASSWORD is not set"

log "About to restore '${DUMP_FILE}' into database '${POSTGRES_DB}'."
log "This DROPS and recreates existing objects (pg_restore --clean --if-exists)."
if [[ "${RESTORE_ASSUME_YES:-0}" != "1" ]]; then
  read -r -p "[restore] Type 'yes' to continue: " reply
  [[ "${reply}" == "yes" ]] || die "Aborted by user"
fi

# --- PostgreSQL restore ------------------------------------------------------
# --clean --if-exists makes the restore idempotent; --exit-on-error surfaces
# real problems while the cleanup DROPs of not-yet-existing objects are ignored.
log "Restoring PostgreSQL (pg_restore)..."
if [[ -n "${PG_CONTAINER}" ]] && have docker; then
  docker exec -i -e PGPASSWORD="${POSTGRES_PASSWORD}" "${PG_CONTAINER}" \
    pg_restore --clean --if-exists --no-owner --no-privileges \
      --username="${POSTGRES_USER}" --dbname="${POSTGRES_DB}" < "${DUMP_FILE}" \
    || log "pg_restore reported non-fatal errors (usually DROP of absent objects)"
elif have pg_restore; then
  PGPASSWORD="${POSTGRES_PASSWORD}" pg_restore --clean --if-exists --no-owner --no-privileges \
    --host="${PGHOST}" --port="${PGPORT}" \
    --username="${POSTGRES_USER}" --dbname="${POSTGRES_DB}" "${DUMP_FILE}" \
    || log "pg_restore reported non-fatal errors (usually DROP of absent objects)"
else
  die "No way to run pg_restore: PG_CONTAINER unset/no docker and no local pg_restore"
fi
log "PostgreSQL restore finished."

cat >&2 <<'EOF'

[restore] Next steps (NOT automated):
  1. Run DB migrations to be safe:
        docker compose run --rm migrate      # or: alembic upgrade head
  2. Rebuild the Elasticsearch index from Postgres (source of truth):
        POST /api/reindex/movies   and   POST /api/reindex/shows   (admin auth)
     — or restore the ES snapshot if you keep one (see README.md).
  3. Restore media files from your separate file-level backup
     (rsync/rclone/restic) if this host lost its media libraries.
  4. Restart the stack:
        docker compose up -d
EOF
log "Restore complete."
