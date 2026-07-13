"""Settings/config-migration export endpoints (NOT disaster recovery).

The JSON export/restore endpoints in this module are a **settings and config
migration** aid: they serialize a redactable subset of database rows (settings,
selected tables) so config can be moved between installs, diffed, or seeded.
The row-by-row restore has no referential-integrity transaction guarantee and
the export omits binary/large data, so it is **not** a disaster-recovery (DR)
mechanism.

Real DR lives in ``deployment/backup/`` (``pg_dump`` custom-format archives +
optional Elasticsearch snapshot + separate media-file backup, with off-site
upload and cron scheduling). The ``/disaster-recovery/*`` endpoints below expose
the *status* of, and a manual *trigger* for, a server-side ``pg_dump`` (which
only works if ``pg_dump`` is on the container PATH); the shell scripts remain
the primary, fully-featured path. See ``deployment/backup/README.md``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
import json
import shutil
import uuid
from typing import Any
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_
from sqlalchemy import types as sqltypes

from streamarr.api.dependencies import CurrentSuperuser, DatabaseSession
from streamarr.api.v1._fs_roots import get_allowed_roots, is_under_allowed
from streamarr.database import Base
from streamarr.models.setting import Setting
from streamarr.schemas.activity_log import ActivityLogCreate
from streamarr.services.activity_log import ActivityLogService
from streamarr.services.backup import BackupService
from streamarr.services.settings import SettingsService, clear_settings_cache

router = APIRouter()

_SENSITIVE_KEY_PARTS = (
    "api_key",
    "client_secret",
    "jwt_secret",
    "password",
    "secret",
    "token",
    "webhook_secret",
)
_REDACTED = "[redacted]"


class SettingsBackup(BaseModel):
    backup_type: str = "settings"
    exported_at: datetime
    include_defaults: bool
    include_secrets: bool
    settings: dict[str, Any] = Field(default_factory=dict)


class SettingsRestoreRequest(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)
    skip_redacted: bool = True


class SettingsRestoreResponse(BaseModel):
    restored_count: int
    skipped_count: int


class DatabaseBackup(BaseModel):
    backup_type: str = "database"
    exported_at: datetime
    include_secrets: bool
    limit_per_table: int
    tables: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    table_counts: dict[str, int] = Field(default_factory=dict)
    truncated_tables: list[str] = Field(default_factory=list)


class DatabaseRestoreRequest(BaseModel):
    tables: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    dry_run: bool = True
    skip_redacted: bool = True
    delete_missing_rows: bool = False
    delete_missing_tables: list[str] = Field(default_factory=list)
    destructive_confirmation: str | None = None


class DatabaseRestoreResponse(BaseModel):
    dry_run: bool
    restored_rows: int
    skipped_rows: int
    deleted_rows: int = 0
    table_counts: dict[str, int] = Field(default_factory=dict)
    deleted_table_counts: dict[str, int] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)


class MediaManifestEntry(BaseModel):
    media_file_guid: uuid.UUID
    media_item_guid: uuid.UUID
    title: str | None = None
    media_type: str | None = None
    file_path: str
    file_name: str | None = None
    file_size: int | None = None
    quality: str | None = None
    format: str | None = None
    exists: bool | None = None


class MediaManifestBackup(BaseModel):
    backup_type: str = "media_manifest"
    exported_at: datetime
    check_exists: bool
    total_files: int
    total_bytes: int
    missing_files: int | None = None
    files: list[MediaManifestEntry] = Field(default_factory=list)


class MediaManifestCopyRequest(BaseModel):
    files: list[MediaManifestEntry] = Field(default_factory=list)
    destination_root: str = Field(min_length=1, max_length=4096)
    dry_run: bool = True
    overwrite: bool = False
    preserve_relative_to: str | None = Field(default=None, max_length=4096)


class MediaManifestCopyItem(BaseModel):
    media_file_guid: uuid.UUID
    source_path: str
    destination_path: str
    status: str
    bytes: int | None = None
    error: str | None = None


class MediaManifestCopyResponse(BaseModel):
    dry_run: bool
    planned_count: int
    copied_count: int
    skipped_count: int
    missing_count: int
    error_count: int
    total_bytes: int
    items: list[MediaManifestCopyItem] = Field(default_factory=list)


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower()
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def _redact_settings(settings: dict[str, Any], include_secrets: bool) -> dict[str, Any]:
    if include_secrets:
        return dict(settings)
    return {
        key: (_REDACTED if _is_sensitive_key(key) and value is not None else value)
        for key, value in settings.items()
    }


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, uuid.UUID)):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _redact_row(table_name: str, row: dict[str, Any], include_secrets: bool) -> dict[str, Any]:
    if include_secrets:
        return row
    redacted = dict(row)
    for key, value in list(redacted.items()):
        if value is not None and (
            _is_sensitive_key(key) or (table_name == "settings" and _is_sensitive_key(str(row.get("key", ""))))
        ):
            redacted[key] = _REDACTED
    return redacted


def _row_has_redacted_secret(table_name: str, row: dict[str, Any]) -> bool:
    for key, value in row.items():
        if value == _REDACTED and (
            _is_sensitive_key(key)
            or (table_name == "settings" and _is_sensitive_key(str(row.get("key", ""))))
        ):
            return True
    return False


def _coerce_restore_value(column, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(column.type, sqltypes.Uuid) and isinstance(value, str):
        return uuid.UUID(value)
    if isinstance(column.type, sqltypes.DateTime) and isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    enum_class = getattr(column.type, "enum_class", None)
    if enum_class is not None and isinstance(value, str):
        return enum_class(value)
    return value


def _coerce_restore_row(table, row: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for column in table.columns:
        if column.name in row:
            output[column.name] = _coerce_restore_value(column, row[column.name])
    return output


def _pk_identity(primary_keys, values: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(values[pk.name] for pk in primary_keys)


def _destination_for_manifest_entry(
    entry: MediaManifestEntry,
    destination_root: Path,
    preserve_relative_to: Path | None,
) -> Path:
    source = Path(entry.file_path).expanduser()
    if preserve_relative_to is not None:
        try:
            relative = source.resolve().relative_to(preserve_relative_to.resolve())
            return (destination_root / relative).resolve()
        except (ValueError, FileNotFoundError):
            pass

    file_name = entry.file_name or source.name
    safe_name = Path(file_name).name
    media_type = (entry.media_type or "media").lower()
    return (destination_root / media_type / str(entry.media_item_guid) / safe_name).resolve()


def _assert_under_root(path: Path, root: Path) -> None:
    if not path.is_relative_to(root):
        raise ValueError("Destination path escapes destination root")


@router.get("/settings", response_model=SettingsBackup)
async def export_settings_backup(
    db: DatabaseSession,
    current_user: CurrentSuperuser,  # noqa: ARG001
    include_defaults: bool = Query(True),
    include_secrets: bool = Query(False),
):
    """Export database-backed settings as a JSON backup."""
    service = SettingsService(db)
    settings = await service.get_all() if include_defaults else {}
    if not include_defaults:
        settings = await BackupService(db).get_settings()

    return SettingsBackup(
        exported_at=datetime.now(UTC),
        include_defaults=include_defaults,
        include_secrets=include_secrets,
        settings=_redact_settings(settings, include_secrets=include_secrets),
    )


@router.get("/database", response_model=DatabaseBackup)
async def export_database_backup(
    db: DatabaseSession,
    current_user: CurrentSuperuser,
    include_secrets: bool = Query(False),
    limit_per_table: int = Query(10_000, ge=1, le=100_000),
):
    """Export database table rows as a JSON **config-migration** payload.

    This is not a disaster-recovery backup: rows are truncated per table, secrets
    are redacted by default, and the row-by-row restore has no referential
    transaction guarantee. For DR use ``deployment/backup/backup.sh`` (pg_dump).
    """
    tables = dict(Base.metadata.tables)
    tables.setdefault(Setting.__tablename__, Setting.__table__)

    exported_tables: dict[str, list[dict[str, Any]]] = {}
    table_counts: dict[str, int] = {}
    truncated_tables: list[str] = []

    backup_service = BackupService(db)
    for table_name in sorted(tables):
        table = tables[table_name]
        rows = await backup_service.dump_table(table, limit_per_table + 1)
        if len(rows) > limit_per_table:
            truncated_tables.append(table_name)
            rows = rows[:limit_per_table]

        serialized_rows: list[dict[str, Any]] = []
        for row in rows:
            serialized = {
                key: _jsonable(value)
                for key, value in dict(row).items()
            }
            serialized_rows.append(
                _redact_row(table_name, serialized, include_secrets=include_secrets)
            )

        exported_tables[table_name] = serialized_rows
        table_counts[table_name] = len(serialized_rows)

    await ActivityLogService(db).create(
        ActivityLogCreate(
            event_type="backup.database_export",
            message="Exported database backup",
            entity_type="backup",
            extra_data=json.dumps(
                {
                    "table_count": len(exported_tables),
                    "include_secrets": include_secrets,
                    "truncated_tables": truncated_tables,
                },
                sort_keys=True,
            ),
        ),
        actor_guid=current_user.guid,
    )

    return DatabaseBackup(
        exported_at=datetime.now(UTC),
        include_secrets=include_secrets,
        limit_per_table=limit_per_table,
        tables=exported_tables,
        table_counts=table_counts,
        truncated_tables=truncated_tables,
    )


@router.post("/database/restore", response_model=DatabaseRestoreResponse)
async def restore_database_backup(
    db: DatabaseSession,
    backup: DatabaseRestoreRequest,
    current_user: CurrentSuperuser,
):
    """Dry-run or upsert rows from a database JSON backup payload."""
    if (
        backup.delete_missing_rows
        and not backup.dry_run
        and backup.destructive_confirmation != "DELETE_MISSING_ROWS"
    ):
        raise HTTPException(
            status_code=400,
            detail="destructive_confirmation must be DELETE_MISSING_ROWS",
        )

    known_tables = dict(Base.metadata.tables)
    known_tables.setdefault(Setting.__tablename__, Setting.__table__)
    sorted_tables = [table for table in Base.metadata.sorted_tables if table.name in known_tables]
    if Setting.__tablename__ not in {table.name for table in sorted_tables}:
        sorted_tables.append(Setting.__table__)

    restored_rows = 0
    skipped_rows = 0
    deleted_rows = 0
    table_counts: dict[str, int] = {}
    deleted_table_counts: dict[str, int] = {}
    errors: list[str] = []

    backup_service = BackupService(db)

    unknown_tables = sorted(set(backup.tables) - set(known_tables))
    for table_name in unknown_tables:
        skipped_rows += len(backup.tables.get(table_name, []))
        errors.append(f"Unknown table skipped: {table_name}")

    for table in sorted_tables:
        rows = backup.tables.get(table.name)
        if not rows:
            continue

        primary_keys = list(table.primary_key.columns)
        if not primary_keys:
            skipped_rows += len(rows)
            errors.append(f"Table has no primary key and was skipped: {table.name}")
            continue

        restore_identities: set[tuple[Any, ...]] = set()
        if backup.delete_missing_rows and table.name in backup.delete_missing_tables:
            for row in rows:
                try:
                    values = _coerce_restore_row(table, row)
                    if all(pk.name in values for pk in primary_keys):
                        restore_identities.add(_pk_identity(primary_keys, values))
                except Exception as exc:
                    errors.append(f"{table.name}: failed to parse restore key: {exc}")

            existing_rows = await backup_service.fetch_table_rows(table)
            deleted_for_table = 0
            for existing_row in existing_rows:
                existing_values = dict(existing_row)
                identity = tuple(existing_values[pk.name] for pk in primary_keys)
                if identity in restore_identities:
                    continue
                try:
                    pk_clause = and_(
                        *[pk == existing_values[pk.name] for pk in primary_keys]
                    )
                    if not backup.dry_run:
                        await backup_service.delete_where(table, pk_clause)
                    deleted_rows += 1
                    deleted_for_table += 1
                except Exception as exc:
                    errors.append(f"{table.name}: delete failed: {exc}")

            if deleted_for_table:
                deleted_table_counts[table.name] = deleted_for_table

        table_restored = 0
        for row in rows:
            if backup.skip_redacted and _row_has_redacted_secret(table.name, row):
                skipped_rows += 1
                continue
            try:
                values = _coerce_restore_row(table, row)
                if not all(pk.name in values for pk in primary_keys):
                    skipped_rows += 1
                    errors.append(f"Row missing primary key skipped in {table.name}")
                    continue

                if not backup.dry_run:
                    pk_clause = and_(
                        *[pk == values[pk.name] for pk in primary_keys]
                    )
                    if await backup_service.row_exists(table, pk_clause):
                        await backup_service.update_where(table, pk_clause, values)
                    else:
                        await backup_service.insert_row(table, values)

                restored_rows += 1
                table_restored += 1
            except Exception as exc:
                skipped_rows += 1
                errors.append(f"{table.name}: {exc}")

        if table_restored:
            table_counts[table.name] = table_restored

    if not backup.dry_run:
        await db.commit()
        # The settings table is upserted via generic table.insert()/update()
        # (BackupService), bypassing SettingsService.set() and therefore the
        # process-global settings cache and its Redis invalidation. Flush and
        # broadcast explicitly so web/worker/scheduler processes pick up
        # restored settings instead of serving stale cached values.
        if (
            Setting.__tablename__ in table_counts
            or Setting.__tablename__ in deleted_table_counts
        ):
            await clear_settings_cache()

    await ActivityLogService(db).create(
        ActivityLogCreate(
            event_type="backup.database_restore",
            message=(
                "Validated database restore backup"
                if backup.dry_run
                else f"Restored {restored_rows} database rows from backup"
            ),
            entity_type="backup",
            extra_data=json.dumps(
                {
                    "dry_run": backup.dry_run,
                    "delete_missing_rows": backup.delete_missing_rows,
                    "restored_rows": restored_rows,
                    "skipped_rows": skipped_rows,
                    "deleted_rows": deleted_rows,
                    "table_counts": table_counts,
                    "deleted_table_counts": deleted_table_counts,
                    "error_count": len(errors),
                },
                sort_keys=True,
            ),
        ),
        actor_guid=current_user.guid,
    )

    return DatabaseRestoreResponse(
        dry_run=backup.dry_run,
        restored_rows=restored_rows,
        skipped_rows=skipped_rows,
        deleted_rows=deleted_rows,
        table_counts=table_counts,
        deleted_table_counts=deleted_table_counts,
        errors=errors,
    )


@router.get("/media-manifest", response_model=MediaManifestBackup)
async def export_media_manifest_backup(
    db: DatabaseSession,
    current_user: CurrentSuperuser,
    check_exists: bool = Query(False),
):
    """Export a manifest of known media files for external file backup tools."""
    manifest_rows = await BackupService(db).get_media_manifest()

    entries: list[MediaManifestEntry] = []
    total_bytes = 0
    missing_files = 0
    for media_file, media_item in manifest_rows:
        exists = None
        if check_exists:
            exists = Path(media_file.file_path).is_file()
            if not exists:
                missing_files += 1
        if media_file.file_size:
            total_bytes += media_file.file_size

        entries.append(
            MediaManifestEntry(
                media_file_guid=media_file.guid,
                media_item_guid=media_file.media_item_guid,
                title=media_item.title,
                media_type=media_item.media_type.value,
                file_path=media_file.file_path,
                file_name=media_file.file_name,
                file_size=media_file.file_size,
                quality=media_file.quality,
                format=media_file.format,
                exists=exists,
            )
        )

    await ActivityLogService(db).create(
        ActivityLogCreate(
            event_type="backup.media_manifest_export",
            message=f"Exported media manifest with {len(entries)} files",
            entity_type="backup",
            extra_data=json.dumps(
                {
                    "total_files": len(entries),
                    "total_bytes": total_bytes,
                    "check_exists": check_exists,
                    "missing_files": missing_files if check_exists else None,
                },
                sort_keys=True,
            ),
        ),
        actor_guid=current_user.guid,
    )

    return MediaManifestBackup(
        exported_at=datetime.now(UTC),
        check_exists=check_exists,
        total_files=len(entries),
        total_bytes=total_bytes,
        missing_files=missing_files if check_exists else None,
        files=entries,
    )


@router.post("/media-manifest/copy", response_model=MediaManifestCopyResponse)
async def copy_media_manifest_files(
    db: DatabaseSession,
    request: MediaManifestCopyRequest,
    current_user: CurrentSuperuser,
):
    """Dry-run or copy files from a media manifest into a destination root."""
    destination_root = Path(request.destination_root).expanduser().resolve()
    preserve_relative_to = (
        Path(request.preserve_relative_to).expanduser()
        if request.preserve_relative_to
        else None
    )

    allowed_roots = await get_allowed_roots(SettingsService(db))

    items: list[MediaManifestCopyItem] = []
    copied_count = skipped_count = missing_count = error_count = total_bytes = 0

    for entry in request.files:
        source_path = Path(entry.file_path).expanduser()
        destination_path = _destination_for_manifest_entry(
            entry,
            destination_root,
            preserve_relative_to,
        )
        bytes_value = entry.file_size
        status_value = "planned"
        error = None

        try:
            # The source path is client-supplied; confine reads to the
            # configured media/storage roots so this endpoint cannot be used to
            # copy arbitrary host files (e.g. /etc/shadow) into a readable dest.
            if not is_under_allowed(source_path.resolve(), allowed_roots):
                raise ValueError(
                    "Source path is outside the configured media/storage roots"
                )
            _assert_under_root(destination_path, destination_root)
            if not source_path.is_file():
                status_value = "missing"
                missing_count += 1
            elif destination_path.exists() and not request.overwrite:
                status_value = "skipped"
                skipped_count += 1
            elif request.dry_run:
                status_value = "planned"
                total_bytes += source_path.stat().st_size
            else:
                destination_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, destination_path)
                status_value = "copied"
                copied_count += 1
                total_bytes += destination_path.stat().st_size
        except Exception as exc:
            status_value = "error"
            error = str(exc)
            error_count += 1

        items.append(
            MediaManifestCopyItem(
                media_file_guid=entry.media_file_guid,
                source_path=str(source_path),
                destination_path=str(destination_path),
                status=status_value,
                bytes=bytes_value,
                error=error,
            )
        )

    planned_count = sum(1 for item in items if item.status == "planned")
    await ActivityLogService(db).create(
        ActivityLogCreate(
            event_type="backup.media_manifest_copy",
            message=(
                "Planned media manifest copy"
                if request.dry_run
                else f"Copied {copied_count} media files from manifest"
            ),
            entity_type="backup",
            extra_data=json.dumps(
                {
                    "dry_run": request.dry_run,
                    "planned_count": planned_count,
                    "copied_count": copied_count,
                    "skipped_count": skipped_count,
                    "missing_count": missing_count,
                    "error_count": error_count,
                    "total_bytes": total_bytes,
                },
                sort_keys=True,
            ),
        ),
        actor_guid=current_user.guid,
    )

    return MediaManifestCopyResponse(
        dry_run=request.dry_run,
        planned_count=planned_count,
        copied_count=copied_count,
        skipped_count=skipped_count,
        missing_count=missing_count,
        error_count=error_count,
        total_bytes=total_bytes,
        items=items,
    )


@router.post("/settings/restore", response_model=SettingsRestoreResponse)
async def restore_settings_backup(
    db: DatabaseSession,
    backup: SettingsRestoreRequest,
    current_user: CurrentSuperuser,
):
    """Restore settings from a settings backup payload."""
    service = SettingsService(db)
    restored_count = 0
    skipped_count = 0
    for key, value in backup.settings.items():
        if backup.skip_redacted and value == _REDACTED:
            skipped_count += 1
            continue
        await service.set(key, value)
        restored_count += 1

    await ActivityLogService(db).create(
        ActivityLogCreate(
            event_type="settings.restore",
            message=f"Restored {restored_count} settings from backup",
            entity_type="settings",
            extra_data=f'{{"skipped_count": {skipped_count}}}',
        ),
        actor_guid=current_user.guid,
    )

    return SettingsRestoreResponse(
        restored_count=restored_count,
        skipped_count=skipped_count,
    )


# ---------------------------------------------------------------------------
# Disaster recovery (real backups): status + server-side pg_dump trigger.
#
# The JSON endpoints above are config migration, not DR. These endpoints expose
# the real DR path (deployment/backup/backup.sh) and, where pg_dump happens to
# be installed in the container, a manual trigger for it.
# ---------------------------------------------------------------------------


class DisasterRecoveryStatus(BaseModel):
    pg_dump_available: bool
    backup_dir: str
    elasticsearch_host: str
    elasticsearch_reindexable: bool = True
    scripts_path: str = "deployment/backup"
    note: str


class PgDumpTriggerResponse(BaseModel):
    status: str
    file: str | None = None
    bytes: int | None = None
    reason: str | None = None


@router.get("/disaster-recovery/status", response_model=DisasterRecoveryStatus)
async def disaster_recovery_status(
    current_user: CurrentSuperuser,  # noqa: ARG001
):
    """Report the real disaster-recovery capabilities of this deployment.

    The JSON export endpoints are config migration only; genuine DR is
    ``deployment/backup/backup.sh`` (pg_dump + optional ES snapshot + media).
    """
    from streamarr.config import settings as app_settings
    from streamarr.workers.backup_worker import backup_dir, pg_dump_available

    available = pg_dump_available()
    note = (
        "Server-side pg_dump is available; POST /disaster-recovery/pg-dump to run it."
        if available
        else (
            "pg_dump is not installed in this container. Use "
            "deployment/backup/backup.sh (runs pg_dump inside the Postgres container)."
        )
    )
    return DisasterRecoveryStatus(
        pg_dump_available=available,
        backup_dir=str(backup_dir()),
        elasticsearch_host=f"{app_settings.elasticsearch.host}:{app_settings.elasticsearch.port}",
        note=note,
    )


@router.post("/disaster-recovery/pg-dump", response_model=PgDumpTriggerResponse)
async def trigger_pg_dump_backup(
    db: DatabaseSession,
    current_user: CurrentSuperuser,
):
    """Trigger a server-side ``pg_dump`` custom-format backup, if available.

    Returns HTTP 503 with guidance when ``pg_dump`` is not installed in the
    container (the default images ship without it) — use the shell scripts.
    """
    from streamarr.workers.backup_worker import run_pg_dump_backup

    result = await run_pg_dump_backup("manual")
    if result.get("skipped") == "pg_dump_unavailable":
        raise HTTPException(
            status_code=503,
            detail=(
                "pg_dump is not available in this container. Run "
                "deployment/backup/backup.sh instead (it dumps inside the "
                "Postgres container)."
            ),
        )

    await ActivityLogService(db).create(
        ActivityLogCreate(
            event_type="backup.pg_dump",
            message=f"Triggered server-side pg_dump backup ({result.get('file')})",
            entity_type="backup",
            extra_data=json.dumps(
                {"bytes": result.get("bytes"), "reason": result.get("reason")},
                sort_keys=True,
            ),
        ),
        actor_guid=current_user.guid,
    )

    return PgDumpTriggerResponse(
        status=result.get("status", "completed"),
        file=result.get("file"),
        bytes=result.get("bytes"),
        reason=result.get("reason"),
    )
