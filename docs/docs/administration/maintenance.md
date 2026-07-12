# Maintenance & Backups

Day-to-day operations: triggering background tasks, exporting and restoring configuration, reading logs, and keeping temporary storage under control.

!!! note "Superuser only"
    Everything on this page requires superuser privileges. See [Users & Groups](user-management.md).

## Background Tasks

Navigate to **Admin** → **Tasks** to manually trigger background jobs. Tasks are grouped into four categories — **Downloads**, **Metadata**, **Cleanup**, and **Search** — each shown as a card with a description and a **Run** button.

| Task | Category | What it does |
|------|----------|--------------|
| Refresh Downloads | Downloads | Polls all active downloads for status updates from the configured download clients |
| Trending Movies / Shows / Games / Music Refresh | Metadata | Updates the trending lists from TMDB, IGDB, and Spotify Charts |
| Backfill Age Ratings | Metadata | Fetches TMDB certifications for movies/shows missing an age rating |
| Clean Orphaned Temp Files | Cleanup | Removes orphaned transcoding temp files (`.ts`, `.m3u8`) older than 2 hours |
| Clean Stale Transcoding Sessions | Cleanup | Removes Redis sessions whose transcode containers are no longer running |
| Full Storage Cleanup | Cleanup | Temp files, old download records, orphaned media files, and duplicates |
| Reindex All / Movies / Shows (Elasticsearch) | Search | Rebuilds the search index |

Most of these also run automatically on a schedule (see [Storage Cleanup](#storage-cleanup) below); triggering them manually just runs them immediately.

### Run History

Below the task cards, **Run History** lists recent runs with a status filter (**All** / **Queued** / **Completed** / **Failed**). Clicking a row opens **Run Details** with the run's lifecycle — when it was queued, completed, or failed, including the error message. Task events are also written to the [activity log](#logs).

## Backups

Navigate to **Admin** → **Settings**, section **Backup and Restore**.

!!! warning "This is config migration, not disaster recovery"
    The JSON export/restore here serializes settings and database rows so you can move configuration between installs or diff it. Exports are truncated per table, secrets are redacted by default, and the restore has no transactional integrity guarantee. For real disaster recovery use the `pg_dump`-based scripts in `deployment/backup/` — see [Deployment → Observability and disaster recovery](../deployment/overview.md#observability-and-disaster-recovery).

=== "Export"

    - **Export Settings** — all database-backed settings as JSON.
    - **Export Database** — table rows as JSON, with per-table counts and a list of truncated tables.

    Sensitive values (API keys, secrets, tokens, passwords) are replaced with `[redacted]` in both exports. Copy the resulting **Backup JSON** somewhere safe.

=== "Restore"

    Paste a backup JSON into **Backup JSON to restore**, then choose:

    - **Dry run** — validates the payload and reports the planned row changes without writing anything.
    - **Skip redacted secrets** — leaves existing secrets untouched instead of overwriting them with `[redacted]`.
    - **Delete missing rows** — optionally deletes rows that are absent from the backup, but only from the tables you list under **Tables allowed to delete from**, and only after typing `DELETE_MISSING_ROWS` into the confirmation field.

    **Restore Database** upserts rows by primary key; **Restore Settings** applies a settings export. A summary and any warnings are shown afterwards.

!!! tip "Always dry-run first"
    Restores default to dry-run for a reason — review the reported row counts and warnings before applying.

For file-level backups, the API additionally offers a media manifest export (`GET /api/backups/media-manifest`) listing every known media file with path and size, and `GET /api/backups/disaster-recovery/status` reports whether a server-side `pg_dump` is available (the default images ship without it).

## Logs

Navigate to **Admin** → **Logs**. The page has two parts:

- **Transcoding session logs** — pick a running or stopped transcoding session, choose how many lines to tail, and **Load** the FFmpeg container output; an **Auto** toggle refreshes continuously. Useful when debugging playback, together with [Transcoding](transcoding.md) and [Monitoring](monitoring.md).
- **Activity Logs** — a filterable audit table of server events (task runs, backup exports/restores, and other admin actions) with **Event Type**, **Severity**, **Entity Type**, and date-range filters.

Signed-in client apps can also push their own log messages to the server (`POST /api/client-logs`). These entries are written into the backend's log stream (logger `pyrate.client`), so they show up in your container logs (e.g. `docker compose logs backend`), not in the admin UI.

## Storage Cleanup

Cleanup runs automatically: orphaned transcode temp files every 15 minutes, stale transcoding sessions every 6 hours, and the **Full Storage Cleanup** every 6 hours. The full cleanup removes expired transcode temp files, prunes old download records (30 days by default), and — when enabled — orphaned media files and duplicates.

Cleanup behaviour is tunable via the storage settings API (`GET`/`PUT /api/settings/storage`): `temp_max_age_hours`, `temp_max_size_gb`, `download_record_max_age_days`, `cleanup_orphaned_files`, and `cleanup_duplicates`.

!!! tip "Protecting favorites"
    Enable **Protect Favorites from Cleanup** in [System Settings](system-configuration.md) to make automatic library cleanup skip any media favorited by at least one user.

Current disk usage per area (library, downloads, transcodes) is shown on the [admin dashboard](dashboard.md).
