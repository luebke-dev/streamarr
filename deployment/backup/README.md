# streamarr.media — Backup & Restore (Disaster Recovery)

This directory holds the **real disaster-recovery (DR)** story for
streamarr.media. It is deliberately separate from the JSON export endpoints under
`/api/backups/*`, which are only a **settings / config migration** aid (they
export a redactable subset of DB rows for moving config between installs) and
are **not** a disaster-recovery mechanism.

## What is backed up

| Component      | How                                   | Restore path |
|----------------|---------------------------------------|--------------|
| PostgreSQL     | `pg_dump --format=custom` (the source of truth) | `pg_restore` (`restore.sh`) |
| Elasticsearch  | ES snapshot API (**optional**)        | **Rebuild from Postgres** via `POST /api/reindex/*`, or restore the snapshot |
| Config files   | `tar` of `.env`, compose, `deployment/` | untar |
| Media files    | **Not** in per-run archives (optional tar) | separate file-level backup (rsync/rclone/restic) |

### Why Elasticsearch is optional

The search index is a **derived** store: every document in it is rebuildable
from PostgreSQL through the admin reindex endpoints
(`POST /api/reindex/movies`, `POST /api/reindex/shows`, …). Taking an ES
snapshot only saves reindex time on large libraries. If you want snapshots,
set `ES_SNAPSHOT_REPO` (and, for a filesystem repo, `ES_SNAPSHOT_REPO_LOCATION`
inside the ES `path.repo` allowlist) in `backup.env`; otherwise the backup
records `elasticsearch: SKIPPED` and DR relies on reindexing.

### Why media is handled separately

Media libraries are typically far larger than everything else combined and
change slowly. Backing them into a fresh tarball every night is wasteful. Use a
dedicated incremental file-level tool (rsync / rclone / restic) against the
`data/library/*` directories. For convenience, `backup.sh` can still tar them
when `BACKUP_INCLUDE_MEDIA=1`.

## Configuration

Copy `backup.env.example` to `backup.env` and edit. `POSTGRES_PASSWORD` is read
from the process environment or the repo-root `.env` if not set in `backup.env`.
`pg_dump`/`pg_restore` live in the Postgres **container**, so by default both
scripts shell into it via `docker exec ${PG_CONTAINER}` (default
`streamarr-db-1`). Set `PG_CONTAINER=""` to use local client tools against
`PGHOST:PGPORT` instead.

## Running a backup

```bash
deployment/backup/backup.sh                 # uses deployment/backup/backup.env
deployment/backup/backup.sh /etc/streamarr-backup.env
```

Output lands in `${BACKUP_ROOT}/<UTC-timestamp>/` with a `MANIFEST.txt`
describing the set. If `RCLONE_REMOTE` or `AWS_S3_TARGET` is configured (and the
matching CLI is installed) the set is also pushed off-site. Local sets older
than `RETENTION_DAYS` are pruned.

## Restoring

```bash
deployment/backup/restore.sh /var/backups/streamarr/20260703T020000Z
# or point straight at a dump:
deployment/backup/restore.sh /path/to/postgres.dump
```

`restore.sh` runs `pg_restore --clean --if-exists` (idempotent), then prints the
follow-up steps it does **not** automate:

1. Run migrations: `docker compose run --rm migrate` (`alembic upgrade head`).
2. Rebuild Elasticsearch: `POST /api/reindex/movies` + `POST /api/reindex/shows`
   (admin auth), or restore the ES snapshot.
3. Restore media from your separate file-level backup if needed.
4. `docker compose up -d`.

Set `RESTORE_ASSUME_YES=1` to skip the interactive confirmation (for automation).

## Scheduling (cron)

```cron
# Nightly full DB + config backup at 02:00, log to syslog
0 2 * * *  cd /root/streamarr.media && deployment/backup/backup.sh >> /var/log/streamarr-backup.log 2>&1
```

Or use a systemd timer wrapping the same command. Verify restores periodically
against a throwaway database — an untested backup is not a backup.

## In-app scheduled backup (optional)

`src/streamarr/workers/backup_worker.py` provides a `scheduled_database_backup`
worker task (daily 02:00) and a manual trigger at
`POST /api/backups/disaster-recovery/pg-dump`. These only work if `pg_dump` is
on the container's `PATH` (it is **not** in the default backend/worker images);
when it is missing they no-op gracefully and point back to these scripts, which
remain the primary, fully-featured path. `GET /api/backups/disaster-recovery/status`
reports availability and the configured backup directory (`STREAMARR_BACKUP_DIR`).
