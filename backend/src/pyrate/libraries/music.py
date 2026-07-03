"""Music library plugin."""

import json
import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import Any

from pyrate.libraries.base import LibraryBase

logger = logging.getLogger(__name__)


class MusicLibraryPlugin(LibraryBase):
    """Plugin for managing music libraries."""

    def get_name(self) -> str:
        return "Music Library"

    def get_library_type(self) -> str:
        return "MUSIC"

    def get_media_item_types(self) -> list[dict[str, Any]]:
        return [
            {"name": "ARTISTS", "label": "Artist", "parent_type": None},
            {"name": "ALBUMS", "label": "Album", "parent_type": "ARTISTS"},
            {"name": "SONGS", "label": "Song", "parent_type": "ALBUMS"},
        ]

    async def get_default_path(self) -> str:
        return "/library/music"

    async def validate_path(self, path: str) -> bool:
        """Validate music library path."""
        try:
            path_obj = Path(path)
            if path_obj.exists():
                return path_obj.is_dir()
            return path_obj.parent.exists() and os.access(path_obj.parent, os.W_OK)
        except Exception as e:
            logger.error("Error validating music library path %s: %s", path, e)
            return False

    async def get_library_stats(self, path: str) -> dict[str, Any]:
        """Get statistics about the music library."""
        stats = {
            "path": path,
            "file_count": 0,
            "total_size": 0,
            "file_types": {},
            "artist_count": 0,
            "album_count": 0,
        }

        try:
            path_obj = Path(path)
            if not path_obj.exists():
                return stats

            audio_extensions = {
                ".mp3",
                ".flac",
                ".m4a",
                ".aac",
                ".ogg",
                ".opus",
                ".wav",
                ".wma",
                ".ape",
                ".alac",
            }

            # Count artists (first level) and albums (second level)
            artist_dirs = [d for d in path_obj.iterdir() if d.is_dir()]
            stats["artist_count"] = len(artist_dirs)

            album_count = 0
            for artist_dir in artist_dirs:
                albums = [d for d in artist_dir.iterdir() if d.is_dir()]
                album_count += len(albums)
            stats["album_count"] = album_count

            for file_path in path_obj.rglob("*"):
                if file_path.is_file():
                    ext = file_path.suffix.lower()
                    if ext in audio_extensions:
                        stats["file_count"] += 1
                        stats["total_size"] += file_path.stat().st_size
                        stats["file_types"][ext] = stats["file_types"].get(ext, 0) + 1

        except Exception as e:
            logger.error("Error getting music library stats for %s: %s", path, e)

        return stats

    async def handle_completed_download(
        self,
        *,
        download_context: dict[str, Any],
        files: list[Path],
        db: Any,
    ) -> dict[str, Any]:
        """Import completed music download into the library."""
        from pyrate.models.media import AvailabilityStatus, MediaFile, MediaItem

        media_item = download_context["media_item"]

        # Navigate the hierarchy: Song -> Album -> Artist
        album = None
        artist = None
        if media_item.parent_guid:
            album = await db.get(MediaItem, media_item.parent_guid)
            if album and album.parent_guid:
                artist = await db.get(MediaItem, album.parent_guid)

        artist_name = self._sanitize_path(artist.title) if artist else "Unknown Artist"
        album_name = self._sanitize_path(album.title) if album else "Unknown Album"
        track_number = media_item.sequence_number or 0

        # Parse disc_number from extra_data for multi-disc albums
        disc_number = 1
        if media_item.extra_data:
            try:
                ed = json.loads(media_item.extra_data) if isinstance(media_item.extra_data, str) else media_item.extra_data
                disc_number = ed.get("disc_number", 1)
            except (json.JSONDecodeError, TypeError):
                pass

        library_path = await self.get_default_path()
        dest_folder = f"{library_path}/{artist_name}/{album_name}"
        os.makedirs(dest_folder, exist_ok=True)

        files_imported = 0
        for file in files:
            extension = file.suffix
            song_title = self._sanitize_path(media_item.title)
            if track_number:
                if disc_number > 1:
                    new_file_name = f"{disc_number}-{track_number:02d} - {song_title}"
                else:
                    new_file_name = f"{track_number:02d} - {song_title}"
            else:
                new_file_name = song_title

            new_file_path = f"{dest_folder}/{new_file_name}{extension}"
            shutil.copy2(str(file), new_file_path)

            probe_data = await self.probe_media_file(new_file_path)

            file_size = os.path.getsize(new_file_path)
            duration = None
            bitrate = None
            if probe_data:
                fmt = probe_data.get("format", {})
                duration = fmt.get("duration")
                if duration is not None:
                    try:
                        duration = float(duration)
                    except (TypeError, ValueError):
                        duration = None
                bitrate = fmt.get("bit_rate")
                if bitrate is not None:
                    try:
                        bitrate = int(bitrate)
                    except (TypeError, ValueError):
                        bitrate = None

            media_file = MediaFile(
                guid=uuid.uuid4(),
                media_item_guid=media_item.guid,
                file_path=new_file_path,
                file_name=f"{new_file_name}{extension}",
                file_size=file_size,
                duration=duration,
                codec=extension.lstrip("."),
                bitrate=bitrate,
                format=extension.lstrip("."),
                probe_data=json.dumps(probe_data) if probe_data else None,
            )
            db.add(media_file)
            await db.commit()
            files_imported += 1
            logger.info("Imported music file: %s -> %s%s", file.name, new_file_name, extension)

        if files_imported > 0:
            media_item.availability_status = AvailabilityStatus.AVAILABLE
            await db.commit()

            try:
                from pyrate.services.redis_event import get_redis_event_service

                redis_service = get_redis_event_service()
                await redis_service.publish_media_item_updated(
                    media_item_id=media_item.guid,
                    update_type="media_available",
                    data={"files_imported": files_imported},
                )
            except Exception as e:
                logger.warning("Failed to publish media_available event: %s", e)

        return {
            "success": files_imported > 0,
            "files_imported": files_imported,
            "song_title": media_item.title,
            **({"error": "No files imported"} if files_imported == 0 else {}),
        }

    @staticmethod
    def _sanitize_path(name: str) -> str:
        """Remove characters that are unsafe for file/directory names."""
        return "".join(c for c in name if c not in r'<>:"/\|?*').strip(". ")

    def get_settings_schema(self) -> dict[str, Any]:
        return {
            "enable_library": {"default": True, "key": "enabled"},
            "library_path": {"default": "/library/music"},
            "enable_on_demand_downloads": {"default": True},
            "enable_prefetch_downloads": {"default": False},
            "download_rules": {"default": []},
            "on_demand_rules": {"default": []},
        }
