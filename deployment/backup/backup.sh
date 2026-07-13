#!/usr/bin/env bash
#
# streamarr.media disaster-recovery backup.
#
# Produces, under a timestamped directory:
#   * postgres.dump       — pg_dump custom-format archive (the source of truth)
#   * elasticsearch.json  — ES snapshot trigger result (optional; reindexable)
#   * config.tar.gz       — small config files (.env, compose, deployment/)
#   * media.tar.gz        — media libraries (optional, usually skipped)
#   * MANIFEST.txt        — human-readable summary of what the set contains
# and optionally uploads the set to an off-site S3-compatible target.
#
# Config comes from (later wins): deployment/backup/backup.env(.example),
# an env file given as $1 or $BACKUP_ENV_FILE, the repo-root .env (POSTGRES_*),
# and the process environment. See backup.env.example for every knob.
#
# Usage:  ./backup.sh [path/to/backup.env]
set -euo pipefail

# --- Resolve locations -------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

log()  { printf '[backup] %s\n' "$*" >&2; }
die()  { printf '[backup] ERROR: %s\n' "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# --- Load configuration ------------------------------------------------------
ENV_FILE="${1:-${BACKUP_ENV_FILE:-${SCRIPT_DIR}/backup.env}}"
if [[ -f "${ENV_FILE}" ]]; then
  log "Loading config from ${ENV_FILE}"
  # shellcheck disable=SC1090
  set -a; source "${ENV_FILE}"; set +a
elif [[ -f "${SCRIPT_DIR}/backup.env.example" ]]; then
  log "No backup.env found; loading defaults from backup.env.example"
  # shellcheck disable=SC1090
  set -a; source "${SCRIPT_DIR}/backup.env.example"; set +a
fi

# Fill POSTGRES_* from the repo-root .env if still unset.
if [[ -z "${POSTGRES_PASSWORD:-}" && -f "${REPO_ROOT}/.env" ]]; then
  log "Reading POSTGRES_* from ${REPO_ROOT}/.env"
  # shellcheck disable=SC1090
  set -a; source <(grep -E '^POSTGRES_' "${REPO_ROOT}/.env" || true); set +a
fi

BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/streamarr}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
PG_CONTAINER="${PG_CONTAINER:-streamarr-db-1}"
POSTGRES_USER="${POSTGRES_USER:-streamarr}"
POSTGRES_DB="${POSTGRES_DB:-streamarr}"
PGHOST="${PGHOST:-127.0.0.1}"
PGPORT="${PGPORT:-5432}"
ES_HOST="${ES_HOST:-127.0.0.1}"
ES_PORT="${ES_PORT:-9200}"
ES_SNAPSHOT_REPO="${ES_SNAPSHOT_REPO:-}"
ES_SNAPSHOT_REPO_LOCATION="${ES_SNAPSHOT_REPO_LOCATION:-}"
BACKUP_INCLUDE_MEDIA="${BACKUP_INCLUDE_MEDIA:-0}"
MEDIA_DIRS="${MEDIA_DIRS:-}"
CONFIG_PATHS="${CONFIG_PATHS:-.env docker-compose.yml deployment}"
RCLONE_REMOTE="${RCLONE_REMOTE:-}"
AWS_S3_TARGET="${AWS_S3_TARGET:-}"

[[ -n "${POSTGRES_PASSWORD:-}" ]] || die "POSTGRES_PASSWORD is not set (env, backup.env, or repo .env)"

TS="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="${BACKUP_ROOT}/${TS}"
mkdir -p "${DEST}"
log "Writing backup set to ${DEST}"

MANIFEST="${DEST}/MANIFEST.txt"
{
  echo "streamarr.media backup"
  echo "created_utc: ${TS}"
  echo "host: $(hostname 2>/dev/null || echo unknown)"
  echo "postgres_db: ${POSTGRES_DB}"
} > "${MANIFEST}"

# --- 1. PostgreSQL: pg_dump custom format ------------------------------------
DUMP_FILE="${DEST}/postgres.dump"
log "Dumping PostgreSQL database '${POSTGRES_DB}'..."
if [[ -n "${PG_CONTAINER}" ]] && have docker; then
  log "  via docker exec ${PG_CONTAINER}"
  docker exec -e PGPASSWORD="${POSTGRES_PASSWORD}" "${PG_CONTAINER}" \
    pg_dump --format=custom --no-owner --no-privileges \
      --username="${POSTGRES_USER}" "${POSTGRES_DB}" > "${DUMP_FILE}"
elif have pg_dump; then
  log "  via local pg_dump against ${PGHOST}:${PGPORT}"
  PGPASSWORD="${POSTGRES_PASSWORD}" pg_dump --format=custom --no-owner --no-privileges \
    --host="${PGHOST}" --port="${PGPORT}" \
    --username="${POSTGRES_USER}" --file="${DUMP_FILE}" "${POSTGRES_DB}"
else
  die "No way to run pg_dump: PG_CONTAINER unset/no docker and no local pg_dump"
fi
[[ -s "${DUMP_FILE}" ]] || die "pg_dump produced an empty archive"
echo "postgres.dump: $(du -h "${DUMP_FILE}" | cut -f1) (pg_dump --format=custom)" >> "${MANIFEST}"
log "  PostgreSQL dump OK ($(du -h "${DUMP_FILE}" | cut -f1))"

# --- 2. Elasticsearch snapshot (optional; index is reindexable) --------------
ES_BASE="http://${ES_HOST}:${ES_PORT}"
if [[ -n "${ES_SNAPSHOT_REPO}" ]] && have curl; then
  log "Triggering Elasticsearch snapshot in repo '${ES_SNAPSHOT_REPO}'..."
  if [[ -n "${ES_SNAPSHOT_REPO_LOCATION}" ]]; then
    curl -sf -X PUT "${ES_BASE}/_snapshot/${ES_SNAPSHOT_REPO}" \
      -H 'Content-Type: application/json' \
      -d "{\"type\":\"fs\",\"settings\":{\"location\":\"${ES_SNAPSHOT_REPO_LOCATION}\"}}" \
      >/dev/null || log "  WARN: could not register snapshot repository (continuing)"
  fi
  SNAP="streamarr-${TS,,}"
  if curl -sf -X PUT "${ES_BASE}/_snapshot/${ES_SNAPSHOT_REPO}/${SNAP}?wait_for_completion=true" \
       -o "${DEST}/elasticsearch.json"; then
    echo "elasticsearch.json: snapshot '${SNAP}' in repo '${ES_SNAPSHOT_REPO}'" >> "${MANIFEST}"
    log "  Elasticsearch snapshot OK (${SNAP})"
  else
    log "  WARN: ES snapshot failed — index is rebuildable from Postgres, continuing"
    echo "elasticsearch: SNAPSHOT FAILED — rebuild via admin reindex endpoints" >> "${MANIFEST}"
  fi
else
  log "Skipping Elasticsearch snapshot (no ES_SNAPSHOT_REPO configured)"
  echo "elasticsearch: SKIPPED — rebuild from Postgres via POST /api/reindex/* after restore" >> "${MANIFEST}"
fi

# --- 3. Config files (small, always) -----------------------------------------
CONFIG_TAR="${DEST}/config.tar.gz"
CONFIG_LIST=()
for p in ${CONFIG_PATHS}; do
  [[ -e "${REPO_ROOT}/${p}" ]] && CONFIG_LIST+=("${p}")
done
if [[ ${#CONFIG_LIST[@]} -gt 0 ]]; then
  log "Archiving config: ${CONFIG_LIST[*]}"
  tar -czf "${CONFIG_TAR}" -C "${REPO_ROOT}" "${CONFIG_LIST[@]}"
  echo "config.tar.gz: ${CONFIG_LIST[*]}" >> "${MANIFEST}"
else
  log "No config paths present to archive"
fi

# --- 4. Media libraries (optional, usually skipped) --------------------------
if [[ "${BACKUP_INCLUDE_MEDIA}" == "1" && -n "${MEDIA_DIRS}" ]]; then
  MEDIA_TAR="${DEST}/media.tar.gz"
  MEDIA_LIST=()
  for d in ${MEDIA_DIRS}; do
    [[ -e "${d}" ]] && MEDIA_LIST+=("${d}")
  done
  if [[ ${#MEDIA_LIST[@]} -gt 0 ]]; then
    log "Archiving media dirs: ${MEDIA_LIST[*]} (this can be large/slow)"
    tar -czf "${MEDIA_TAR}" "${MEDIA_LIST[@]}"
    echo "media.tar.gz: ${MEDIA_LIST[*]}" >> "${MANIFEST}"
  fi
else
  log "Skipping media archive (BACKUP_INCLUDE_MEDIA=${BACKUP_INCLUDE_MEDIA})"
  echo "media: SKIPPED — back up libraries with rsync/rclone/restic separately" >> "${MANIFEST}"
fi

# --- 5. Off-site upload (optional) -------------------------------------------
if [[ -n "${RCLONE_REMOTE}" ]] && have rclone; then
  log "Uploading to rclone remote ${RCLONE_REMOTE}/${TS}"
  rclone copy "${DEST}" "${RCLONE_REMOTE}/${TS}" \
    || log "  WARN: rclone upload failed (local copy retained)"
elif [[ -n "${AWS_S3_TARGET}" ]] && have aws; then
  log "Uploading to ${AWS_S3_TARGET}/${TS}"
  aws s3 cp --recursive "${DEST}" "${AWS_S3_TARGET}/${TS}" \
    || log "  WARN: aws s3 upload failed (local copy retained)"
else
  log "No off-site target configured (or CLI missing) — keeping local copy only"
fi

# --- 6. Retention ------------------------------------------------------------
if [[ "${RETENTION_DAYS}" -gt 0 ]]; then
  log "Pruning local backup sets older than ${RETENTION_DAYS} days"
  find "${BACKUP_ROOT}" -mindepth 1 -maxdepth 1 -type d -mtime "+${RETENTION_DAYS}" \
    -exec rm -rf {} + 2>/dev/null || true
fi

log "Backup complete: ${DEST}"
cat "${MANIFEST}" >&2
