"""Reconcile files discovered by library plugins with the media database.

The scanner deliberately keeps discovery (plugins) separate from persistence.
This mirrors Jellyfin's library refresh shape while preserving Streamarr's
plugin architecture: plugins describe files, this service assigns them to
existing media items or creates the smallest required hierarchy.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.metadata.local import clean_provider_ids, read_local_metadata
from streamarr.models.library import Library
from streamarr.models.media import (
    AvailabilityStatus,
    MediaExternalId,
    MediaFile,
    MediaItem,
    MediaType,
)
from streamarr.services.artwork_storage import store_local_artwork


@dataclass(slots=True)
class LibraryReconcileResult:
    discovered: int = 0
    added: int = 0
    updated: int = 0
    removed: int = 0
    skipped: int = 0
    probe_file_guids: list[str] = field(default_factory=list)
    media_item_guids: list[str] = field(default_factory=list)


class LibraryScanIncompleteError(RuntimeError):
    """Discovery did not produce a trustworthy complete snapshot."""


def _key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _file_rows(entry: dict[str, Any]) -> list[dict[str, Any]]:
    if entry.get("files"):
        return [dict(file) for file in entry["files"] if file.get("path")]
    path = entry.get("path") or entry.get("file_path")
    return [{**entry, "path": path}] if path and Path(str(path)).suffix else []


def _is_ignored(root: Path, path: Path) -> bool:
    """Apply one central ignore policy to every library plugin result."""
    relative = path.relative_to(root)
    ignored_names = {"@eadir", "sample", "samples", "extras", "trailers"}
    if any(
        part.casefold() in ignored_names or part.startswith(".")
        for part in relative.parts
    ):
        return True
    if "sample" in path.stem.casefold() and path.stat().st_size < 100 * 1024 * 1024:
        return True
    parent = path.parent
    while parent == root or root in parent.parents:
        if (parent / ".ignore").exists():
            return True
        if parent == root:
            break
        parent = parent.parent
    return False


class LibraryScanner:
    """Idempotently assign discovered files to Streamarr media items."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def reconcile(
        self,
        library: Library,
        discovered: list[dict[str, Any]],
        *,
        root_path: str | Path | None = None,
        scan_id: uuid.UUID | None = None,
    ) -> LibraryReconcileResult:
        result = LibraryReconcileResult()
        root = Path(root_path or library.path).resolve(strict=False)
        scan_id = scan_id or uuid.uuid4()
        # A temporarily unavailable mount must never look like an empty
        # library and cause every file association to be removed.
        if not root.is_dir():
            raise LibraryScanIncompleteError(f"Library path is unavailable: {root}")
        entries = [(entry, file) for entry in discovered for file in _file_rows(entry)]
        result.discovered = len(entries)
        safe_entries = []
        for entry, file in entries:
            resolved = Path(str(file["path"])).resolve(strict=False)
            if resolved != root and root not in resolved.parents:
                result.skipped += 1
                continue
            if _is_ignored(root, resolved):
                result.skipped += 1
                continue
            try:
                stat = resolved.stat()
            except OSError:
                result.skipped += 1
                continue
            identity_key = (
                f"fs:{stat.st_dev}:{stat.st_ino}"
                if stat.st_ino
                else f"meta:{stat.st_size}:{stat.st_mtime_ns}"
            )
            normalized_file = {
                **file,
                "size": file.get("size") or file.get("file_size") or stat.st_size,
                "filesystem_device": stat.st_dev,
                "filesystem_inode": stat.st_ino,
                "modified_ns": stat.st_mtime_ns,
                "identity_key": identity_key,
            }
            safe_entries.append((entry, normalized_file, resolved))
        current_paths = {str(path) for _, _, path in safe_entries}

        root_prefix = f"{root}/"
        existing_files = list(
            (
                await self.db.execute(
                    select(MediaFile).where(
                        or_(
                            and_(
                                MediaFile.library_guid == library.guid,
                                or_(
                                    MediaFile.library_root == str(root),
                                    and_(
                                        MediaFile.library_root.is_(None),
                                        or_(
                                            MediaFile.file_path == str(root),
                                            MediaFile.file_path.startswith(root_prefix),
                                        ),
                                    ),
                                ),
                            ),
                            and_(
                                MediaFile.library_guid.is_(None),
                                or_(
                                    MediaFile.file_path == str(root),
                                    MediaFile.file_path.startswith(root_prefix),
                                ),
                            ),
                        )
                    )
                )
            ).scalars()
        )
        by_path = {
            str(Path(row.file_path).resolve(strict=False)): row
            for row in existing_files
        }
        by_identity: dict[str, MediaFile] = {}
        duplicate_identities: set[str] = set()
        for existing in existing_files:
            if not existing.identity_key:
                continue
            if existing.identity_key in by_identity:
                duplicate_identities.add(existing.identity_key)
            else:
                by_identity[existing.identity_key] = existing
        for duplicate in duplicate_identities:
            by_identity.pop(duplicate, None)

        # Discovery plugins currently return a list rather than an explicit
        # success envelope. If an established library suddenly yields no files
        # while its root is non-empty, fail closed instead of deleting records.
        known_extensions = {
            Path(row.file_path).suffix.casefold() for row in existing_files
        }
        media_still_present = (
            any(
                candidate.is_file() and candidate.suffix.casefold() in known_extensions
                for candidate in root.rglob("*")
            )
            if existing_files and not safe_entries
            else False
        )
        if media_still_present:
            raise LibraryScanIncompleteError(
                f"Library scan returned no files for non-empty path: {root}"
            )

        for entry, file, resolved in safe_entries:
            path = str(resolved)
            row = by_path.get(path)
            renamed = False
            if row is None and file.get("identity_key"):
                # Preserve the MediaFile GUID and all derived data across a
                # rename/move within the same configured root.
                row = by_identity.get(str(file["identity_key"]))
                if row is not None:
                    renamed = row.file_path != path
                    row.file_path = path
                    row.file_name = (
                        file.get("name")
                        or file.get("filename")
                        or file.get("file_name")
                        or resolved.name
                    )
            if row:
                row.library_guid = library.guid
                row.library_root = str(root)
                row.last_seen_scan_id = scan_id
                changed = renamed or self._update_file(row, file)
                result.updated += int(changed)
                item = await self.db.get(MediaItem, row.media_item_guid)
                if item:
                    local_changed = await self._apply_local_metadata(
                        item, self._enrich_local(entry, resolved, library.type)
                    )
                    await self._mark_available(item)
                    if changed or local_changed:
                        result.media_item_guids.append(str(item.guid))
                if changed or not row.probe_data:
                    result.probe_file_guids.append(str(row.guid))
                continue

            item = await self._resolve_item(library.type, entry, Path(path))
            row = MediaFile(
                media_item_guid=item.guid,
                library_guid=library.guid,
                library_root=str(root),
                filesystem_device=file.get("filesystem_device"),
                filesystem_inode=file.get("filesystem_inode"),
                modified_ns=file.get("modified_ns"),
                identity_key=file.get("identity_key"),
                last_seen_scan_id=scan_id,
                file_path=path,
                file_name=file.get("name")
                or file.get("filename")
                or file.get("file_name")
                or Path(path).name,
                file_size=file.get("size") or file.get("file_size"),
                quality=file.get("quality") or entry.get("quality"),
                format=file.get("format")
                or file.get("ext")
                or Path(path).suffix.lstrip("."),
                imported_at=datetime.now(UTC),
            )
            self.db.add(row)
            await self.db.flush()
            await self._mark_available(item)
            result.added += 1
            result.probe_file_guids.append(str(row.guid))
            result.media_item_guids.append(str(item.guid))

        # Scope removals strictly to this library root. Metadata items are kept,
        # like Jellyfin's offline records, so history/favourites can recover.
        for row in existing_files:
            resolved = Path(row.file_path).resolve(strict=False)
            if resolved != root and root not in resolved.parents:
                continue
            if str(resolved) in current_paths:
                continue
            item = await self.db.get(MediaItem, row.media_item_guid)
            await self.db.delete(row)
            await self.db.flush()
            if item and not await self._has_files(item.guid):
                item.availability_status = AvailabilityStatus.UNKNOWN
                await self._refresh_parent_availability(item.parent_guid)
            result.removed += 1

        # The API/worker orchestration owns the transaction and commits the
        # reconciliation together with its ActivityLog entry.
        await self.db.flush()
        return result

    @staticmethod
    def _update_file(row: MediaFile, info: dict[str, Any]) -> bool:
        values = {
            "file_name": info.get("name")
            or info.get("filename")
            or info.get("file_name"),
            "file_size": info.get("size") or info.get("file_size"),
            "quality": info.get("quality"),
            "format": info.get("format") or info.get("ext") or info.get("extension"),
            "filesystem_device": info.get("filesystem_device"),
            "filesystem_inode": info.get("filesystem_inode"),
            "modified_ns": info.get("modified_ns"),
            "identity_key": info.get("identity_key"),
        }
        changed = False
        for attribute, value in values.items():
            if value is not None and getattr(row, attribute) != value:
                setattr(
                    row,
                    attribute,
                    str(value).lstrip(".") if attribute == "format" else value,
                )
                changed = True
        return changed

    async def _has_files(self, item_guid) -> bool:
        return (
            await self.db.execute(
                select(MediaFile.guid)
                .where(MediaFile.media_item_guid == item_guid)
                .limit(1)
            )
        ).scalar_one_or_none() is not None

    async def _mark_available(self, item: MediaItem) -> None:
        current = item
        while current:
            current.availability_status = AvailabilityStatus.AVAILABLE
            current = (
                await self.db.get(MediaItem, current.parent_guid)
                if current.parent_guid
                else None
            )

    async def _refresh_parent_availability(self, parent_guid) -> None:
        while parent_guid:
            parent = await self.db.get(MediaItem, parent_guid)
            if not parent:
                return
            has_available_child = (
                await self.db.execute(
                    select(MediaItem.guid)
                    .where(
                        MediaItem.parent_guid == parent.guid,
                        MediaItem.availability_status == AvailabilityStatus.AVAILABLE,
                    )
                    .limit(1)
                )
            ).scalar_one_or_none() is not None
            parent.availability_status = (
                AvailabilityStatus.AVAILABLE
                if await self._has_files(parent.guid) or has_available_child
                else AvailabilityStatus.UNKNOWN
            )
            parent_guid = parent.parent_guid

    async def _find_item(
        self,
        media_type: MediaType,
        title: str,
        parent_guid=None,
        sequence=None,
        release_year=None,
    ) -> MediaItem | None:
        query = select(MediaItem).where(MediaItem.media_type == media_type)
        if parent_guid is None:
            query = query.where(MediaItem.parent_guid.is_(None))
        else:
            query = query.where(MediaItem.parent_guid == parent_guid)
        if sequence is not None:
            query = query.where(MediaItem.sequence_number == sequence)
        candidates = (await self.db.execute(query)).scalars().all()
        if sequence is not None:
            return candidates[0] if candidates else None
        if release_year is not None:
            candidates = [
                item
                for item in candidates
                if item.release_date and item.release_date.year == release_year
            ]
        return next(
            (item for item in candidates if _key(item.title) == _key(title)), None
        )

    async def _get_or_create(
        self, media_type, title, parent=None, sequence=None, **kwargs
    ):
        release_date = kwargs.get("release_date")
        item = await self._find_item(
            media_type,
            title,
            parent,
            sequence,
            release_date.year if release_date else None,
        )
        if item:
            return item
        item = MediaItem(
            media_type=media_type,
            title=title,
            parent_guid=parent,
            sequence_number=sequence,
            availability_status=AvailabilityStatus.UNKNOWN,
            **kwargs,
        )
        self.db.add(item)
        await self.db.flush()
        return item

    async def _apply_local_metadata(
        self, item: MediaItem, info: dict[str, Any]
    ) -> bool:
        local = info.get("_local_metadata")
        if not isinstance(local, dict):
            return False
        before = (
            item.title,
            item.original_title,
            item.description,
            item.tagline,
            item.content_rating,
            item.release_date,
            item.poster_path,
            item.backdrop_path,
            dict(item.extra_data or {}),
        )
        values = local.get("values") or {}
        extra = dict(item.extra_data or {})
        locked_fields = set(extra.get("locked_fields") or [])
        locked_fields.update(local.get("locked_fields") or [])
        provenance = dict(extra.get("metadata_provenance") or {})
        field_map = {
            "title": "title",
            "original_title": "original_title",
            "description": "description",
            "tagline": "tagline",
            "content_rating": "content_rating",
        }
        for source_name, attribute in field_map.items():
            value = values.get(source_name)
            if value:
                setattr(item, attribute, value)
                provenance[attribute] = "local"
        if values.get("year") and not item.release_date:
            try:
                item.release_date = datetime(int(values["year"]), 1, 1, tzinfo=UTC)
                provenance["release_date"] = "local"
            except (TypeError, ValueError):
                pass
        if values.get("release_date"):
            try:
                parsed = datetime.fromisoformat(str(values["release_date"]).replace("Z", "+00:00"))
                item.release_date = parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
                provenance["release_date"] = "local"
            except ValueError:
                pass

        for provider, external_id in (local.get("external_ids") or {}).items():
            existing = await self.db.scalar(
                select(MediaExternalId).where(
                    MediaExternalId.provider == provider,
                    MediaExternalId.external_id == str(external_id),
                )
            )
            if existing is None:
                self.db.add(
                    MediaExternalId(
                        media_item_guid=item.guid,
                        provider=provider,
                        external_id=str(external_id),
                    )
                )

        for image_type, attribute in (("poster", "poster_path"), ("backdrop", "backdrop_path")):
            source = local.get(f"{image_type}_path")
            if source:
                stored = store_local_artwork(item.guid, image_type, Path(source))
                if stored:
                    setattr(item, attribute, stored)
                    provenance[attribute] = "local"
        extra["locked_fields"] = sorted(locked_fields)
        extra["metadata_provenance"] = provenance
        if local.get("source_path"):
            extra["local_metadata_path"] = local["source_path"]
        item.extra_data = extra
        after = (
            item.title,
            item.original_title,
            item.description,
            item.tagline,
            item.content_rating,
            item.release_date,
            item.poster_path,
            item.backdrop_path,
            dict(item.extra_data or {}),
        )
        return before != after

    @staticmethod
    def _enrich_local(
        info: dict[str, Any], path: Path, library_type: str
    ) -> dict[str, Any]:
        local = read_local_metadata(path, library_type)
        return {
            **info,
            **local.values,
            "_local_metadata": {
                "values": local.values,
                "external_ids": local.external_ids,
                "locked_fields": sorted(local.locked_fields),
                "poster_path": str(local.poster_path) if local.poster_path else None,
                "backdrop_path": str(local.backdrop_path) if local.backdrop_path else None,
                "source_path": str(local.source_path) if local.source_path else None,
            },
        }

    async def _resolve_item(self, library_type: str, info: dict[str, Any], path: Path):
        info = self._enrich_local(info, path, library_type)
        kind = library_type.upper()
        if kind == "SHOWS":
            show_title = str(info.get("show_name") or path.parent.parent.name)
            season_no = int(info.get("season") or 0)
            episode_no = int(info.get("episode") or 0)
            show = await self._get_or_create(MediaType.SHOWS, clean_provider_ids(show_title))
            season = await self._get_or_create(
                MediaType.SEASONS, f"Season {season_no}", show.guid, season_no
            )
            title = str(info.get("title") or path.stem)
            item = await self._get_or_create(
                MediaType.EPISODES, title, season.guid, episode_no
            )
            if info.get("episode_end"):
                extra = dict(item.extra_data or {})
                extra["episode_end"] = int(info["episode_end"])
                item.extra_data = extra
            await self._apply_local_metadata(item, info)
            return item

        if kind == "MUSIC":
            artist = await self._get_or_create(
                MediaType.ARTISTS, str(info.get("artist") or "Unknown Artist")
            )
            album = await self._get_or_create(
                MediaType.ALBUMS,
                str(info.get("album") or "Unknown Album"),
                artist.guid,
            )
            item = await self._get_or_create(
                MediaType.SONGS,
                str(info.get("title") or path.stem),
                album.guid,
                info.get("track"),
            )
            await self._apply_local_metadata(item, info)
            return item

        type_name = str(info.get("media_type") or kind).upper()
        if type_name == "BOOKS" and info.get("type") == "audiobook":
            type_name = "AUDIOBOOKS"
        try:
            media_type = MediaType[type_name]
        except KeyError:
            media_type = MediaType[kind]
        title = clean_provider_ids(str(info.get("title") or path.stem))
        kwargs = {}
        if info.get("year"):
            kwargs["release_date"] = datetime(int(info["year"]), 1, 1, tzinfo=UTC)
        if kind == "GAMES":
            kwargs["extra_data"] = {
                "lightrays": {"profile": "retro"},
                **({"platform": info["platform"]} if info.get("platform") else {}),
            }
        item = await self._get_or_create(media_type, title, **kwargs)
        await self._apply_local_metadata(item, info)
        return item
