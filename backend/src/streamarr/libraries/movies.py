"""Movie library plugin."""

import asyncio
import json
import logging
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from streamarr.libraries.base import LibraryBase, extract_naming_metadata
from streamarr.libraries.video_helpers import (
    VIDEO_EXTENSIONS,
    iter_video_files,
    library_video_stats,
    safe_library_child_path,
    validate_library_path,
    video_file_info,
)
from streamarr.parsers.release_parser import ReleaseParser

logger = logging.getLogger(__name__)


class MovieLibraryPlugin(LibraryBase):
    """Plugin for managing movie libraries."""

    def get_name(self) -> str:
        return "Movie Library"

    def get_library_type(self) -> str:
        return "MOVIES"

    async def get_default_path(self) -> str:
        return "/library/movies"

    async def validate_path(self, path: str) -> bool:
        """Validate movie library path."""
        return validate_library_path(path)

    async def get_library_stats(self, path: str) -> dict[str, Any]:
        """Get statistics about the movie library."""
        return library_video_stats(path)

    # ==================== Media-Specific Operations ====================

    def _get_video_extensions(self) -> set[str]:
        """Get supported video extensions for movies."""
        return set(VIDEO_EXTENSIONS)

    async def get_supported_extensions(self) -> list[str]:
        """Get list of supported file extensions for movies."""
        return list(self._get_video_extensions())

    async def scan_library(self, path: str) -> list[dict[str, Any]]:
        """
        Scan library path for movie files.

        Args:
            path: The library path to scan

        Returns:
            list[dict]: List of discovered movie files with metadata
        """
        discovered = []

        try:
            path_obj = Path(path)
            if not path_obj.exists():
                logger.warning("Library path does not exist: %s", path)
                return discovered

            for file_path in iter_video_files(path_obj):
                file_info = video_file_info(file_path)

                # Extract metadata from filename
                metadata = await self.extract_metadata_from_filename(file_path.name)
                file_info.update(metadata)

                discovered.append(file_info)

            logger.info("Found %s movie files in %s", len(discovered), path)

        except Exception as e:
            logger.error("Error scanning movie library %s: %s", path, e)

        return discovered

    async def extract_metadata_from_filename(self, filename: str) -> dict[str, Any]:
        """
        Extract metadata from movie filename.

        Supports patterns like:
        - Movie Name (2023).mkv
        - Movie.Name.2023.1080p.BluRay.x264.mkv
        - Movie_Name_2023_720p.mp4

        Args:
            filename: The filename to parse

        Returns:
            dict: Extracted metadata (title, year, quality, etc.)
        """
        metadata: dict[str, Any] = {}

        # Remove extension
        name = Path(filename).stem

        # Try to extract year
        year_pattern = r"\b(19\d{2}|20\d{2})\b"
        year_match = re.search(year_pattern, name)
        if year_match:
            metadata["year"] = int(year_match.group(1))
            # Remove year and everything after for title extraction
            name_for_title = name[: year_match.start()].strip()
        else:
            name_for_title = name

        # Extract quality
        quality_patterns = {
            "2160p": ["2160p", "4K", "UHD"],
            "1080p": ["1080p", "FHD"],
            "720p": ["720p", "HD"],
            "480p": ["480p", "SD"],
        }

        for quality, patterns in quality_patterns.items():
            if any(p.lower() in name.lower() for p in patterns):
                metadata["quality"] = quality
                break

        # Extract title (replace dots, underscores, dashes with spaces)
        title = re.sub(r"[._-]+", " ", name_for_title).strip()
        # Remove extra spaces
        title = re.sub(r"\s+", " ", title)

        if title:
            metadata["title"] = title

        # Detect release type
        if "BluRay" in name or "Blu-Ray" in name:
            metadata["source"] = "BluRay"
        elif "WEB-DL" in name or "WEBRip" in name:
            metadata["source"] = "WEB"
        elif "HDTV" in name:
            metadata["source"] = "HDTV"
        elif "DVDRip" in name or "DVD" in name:
            metadata["source"] = "DVD"

        return metadata

    async def format_file_path(
        self, media_info: dict[str, Any], library_path: str
    ) -> str:
        """
        Generate the proper file path for a movie within library.

        Format: /library/movies/Movie Name (Year)/Movie Name (Year).ext

        Args:
            media_info: Media metadata (title, year, etc.)
            library_path: Base library path

        Returns:
            str: Formatted path for the movie file
        """
        title = media_info.get("title", "Unknown")
        year = media_info.get("year", "")

        # Sanitize title
        safe_title = "".join(
            c for c in title if c.isalnum() or c in (" ", "-", "_")
        ).strip()

        # Create folder name with year if available
        if year:
            folder_name = f"{safe_title} ({year})"
        else:
            folder_name = safe_title

        # Return directory path (actual file will be placed in this directory)
        return os.path.join(library_path, folder_name)

    async def validate_media_file(self, file_path: str) -> bool:
        """
        Validate that a file is a valid movie file.

        Args:
            file_path: Path to the file to validate

        Returns:
            bool: True if file is valid movie file
        """
        try:
            path = Path(file_path)
            if not path.is_file():
                return False

            # Check extension
            if path.suffix.lower() not in self._get_video_extensions():
                return False

            # Check minimum file size (avoid sample files)
            # Minimum 50MB
            if path.stat().st_size < 50 * 1024 * 1024:
                logger.warning("File %s is too small to be a movie", file_path)
                return False

            return True

        except Exception as e:
            logger.error("Error validating movie file %s: %s", file_path, e)
            return False

    async def get_metadata_provider(self) -> str | None:
        """Get the preferred metadata provider for movies."""
        return "tmdb"

    async def match_media(self, file_info: dict[str, Any]) -> dict[str, Any] | None:
        """
        Match a movie file to TMDB metadata.

        This is a placeholder - actual implementation would call TMDB API.

        Args:
            file_info: Information about the movie file

        Returns:
            dict | None: Matched movie metadata or None if no match found
        """
        # Metadata matching is not wired to a provider from this hook; a None
        # result means "no automatic match" and callers handle it. (This path
        # is currently unused — enrichment goes through the metadata services.)
        return None

    # ==================== Release Metadata Extraction ====================

    async def extract_release_metadata(self, release_title: str) -> dict[str, Any]:
        """
        Extract metadata from a movie release title.

        Parses the release name to extract quality, codec, source, language,
        and other metadata useful for release selection and scoring.

        Args:
            release_title: The full release title to parse

        Returns:
            dict: Extracted metadata
        """
        metadata = {
            "original_title": release_title,
        }

        # Extract resolution and quality
        resolution = ReleaseParser.extract_resolution(release_title)
        if resolution:
            metadata["resolution"] = resolution
            metadata["quality"] = resolution  # e.g., "1080p", "2160p"

        # Extract source
        source = ReleaseParser.extract_source(release_title)
        if source:
            metadata["source"] = source

        # Extract codecs
        video_codec = ReleaseParser.extract_video_codec(release_title)
        if video_codec:
            metadata["video_codec"] = video_codec

        audio_codecs = ReleaseParser.extract_audio_codec(release_title)
        if audio_codecs:
            metadata["audio_codecs"] = audio_codecs
            metadata["audio_codec"] = audio_codecs[0]  # Primary codec

        # Extract languages
        languages = ReleaseParser.extract_languages(release_title)
        if languages:
            metadata["languages"] = languages

        # Extract audio channels
        channels = ReleaseParser.extract_audio_channels(release_title)
        if channels:
            metadata["audio_channels"] = channels

        # Extract release group
        release_group = ReleaseParser.extract_release_group(release_title)
        if release_group:
            metadata["release_group"] = release_group

        # Extract container
        container = ReleaseParser.extract_container(release_title)
        if container:
            metadata["container"] = container

        # Special markers
        metadata["is_hdr"] = ReleaseParser.has_hdr(release_title)
        metadata["is_dolby_vision"] = ReleaseParser.has_dolby_vision(release_title)
        metadata["is_remux"] = ReleaseParser.is_remux(release_title)
        metadata["is_3d"] = ReleaseParser.is_3d(release_title)

        is_proper, is_repack = ReleaseParser.has_proper_or_repack(release_title)
        metadata["is_proper"] = is_proper
        metadata["is_repack"] = is_repack

        # Quality flags
        metadata["is_low_quality"] = ReleaseParser.is_low_quality(release_title)

        return metadata

    async def score_release(
        self, metadata: dict[str, Any], preferences: dict[str, Any] | None = None
    ) -> float:
        """
        Calculate a quality score for a movie release.

        Score ranges from 0-100, with higher scores indicating better quality.
        Considers resolution, source, codec, and other quality factors.

        Args:
            metadata: Release metadata from extract_release_metadata()
            preferences: Optional user preferences

        Returns:
            float: Quality score (0-100)
        """
        score = 0.0

        # Resolution scoring (0-25 points)
        resolution = metadata.get("resolution", "").lower()
        if preferences:
            res_weights = preferences.get("resolution", {})
            if resolution in ("2160p", "4320p"):
                score += (
                    res_weights.get("2160p", 25)
                    if resolution == "2160p"
                    else res_weights.get("4320p", 25)
                )
            elif resolution == "1080p":
                score += res_weights.get("1080p", 20)
            elif resolution == "720p":
                score += res_weights.get("720p", 10)
            elif resolution == "480p":
                score += res_weights.get("480p", 5)
        else:
            if resolution == "2160p" or resolution == "4320p":
                score += 25
            elif resolution == "1080p":
                score += 20
            elif resolution == "720p":
                score += 10
            elif resolution == "480p":
                score += 5

        # Source scoring (0-20 points)
        source = metadata.get("source", "").lower()
        if preferences:
            src_weights = preferences.get("source", {})
            if source == "bluray":
                score += src_weights.get("bluray", 20)
            elif source == "remux":
                score += src_weights.get("remux", 20)
            elif source == "web-dl":
                score += src_weights.get("web-dl", 15)
            elif source == "webrip":
                score += src_weights.get("webrip", 12)
            elif source == "hdtv":
                score += src_weights.get("hdtv", 8)
            elif source == "dvd":
                score += src_weights.get("dvd", 5)
            elif source == "screener":
                score += src_weights.get("screener", 2)
            elif source in ("cam", "telesync", "telecine"):
                score += src_weights.get("cam", 1)
        else:
            if source == "bluray" or source == "remux":
                score += 20
            elif source == "web-dl":
                score += 15
            elif source == "webrip":
                score += 12
            elif source == "hdtv":
                score += 8
            elif source == "dvd":
                score += 5
            elif source == "screener":
                score += 2
            elif source in ("cam", "telesync", "telecine"):
                score += 1

        # Codec scoring (0-15 points)
        video_codec = metadata.get("video_codec", "").lower()
        if preferences:
            codec_weights = preferences.get("codec", {})
            if video_codec == "h265":
                score += codec_weights.get("h265", 15)
            elif video_codec == "av1":
                score += codec_weights.get("av1", 15)
            elif video_codec == "h264":
                score += codec_weights.get("h264", 12)
            elif video_codec in ["xvid", "divx"]:
                score += codec_weights.get(video_codec, 5)
        else:
            if video_codec == "h265" or video_codec == "av1":
                score += 15
            elif video_codec == "h264":
                score += 12
            elif video_codec in ["xvid", "divx"]:
                score += 5

        # Audio codec scoring (0-10 points)
        audio_codecs = metadata.get("audio_codecs", [])
        if preferences:
            audio_weights = preferences.get("audio", {})
            if "truehd" in audio_codecs:
                score += audio_weights.get("truehd", 10)
            elif "dts-hd" in audio_codecs:
                score += audio_weights.get("dts-hd", 10)
            elif "atmos" in audio_codecs:
                score += audio_weights.get("atmos", 10)
            elif "dts" in audio_codecs:
                score += audio_weights.get("dts", 8)
            elif "eac3" in audio_codecs:
                score += audio_weights.get("eac3", 6)
            elif "ac3" in audio_codecs:
                score += audio_weights.get("ac3", 6)
            elif "aac" in audio_codecs:
                score += audio_weights.get("aac", 4)
        else:
            if (
                "truehd" in audio_codecs
                or "dts-hd" in audio_codecs
                or "atmos" in audio_codecs
            ):
                score += 10
            elif "dts" in audio_codecs:
                score += 8
            elif "eac3" in audio_codecs or "ac3" in audio_codecs:
                score += 6
            elif "aac" in audio_codecs:
                score += 4

        # Special features bonus (0-10 points)
        hdr_bonus = preferences.get("hdr_bonus", 5) if preferences else 5
        dv_bonus = preferences.get("dolby_vision_bonus", 5) if preferences else 5
        remux_bonus = preferences.get("remux_bonus", 3) if preferences else 3
        if metadata.get("is_hdr", False):
            score += hdr_bonus
        if metadata.get("is_dolby_vision", False):
            score += dv_bonus
        if metadata.get("is_remux", False):
            score += remux_bonus

        # PROPER/REPACK bonus (0-5 points)
        proper_bonus = preferences.get("proper_bonus", 5) if preferences else 5
        repack_bonus = preferences.get("repack_bonus", 3) if preferences else 3
        if metadata.get("is_proper", False):
            score += proper_bonus
        if metadata.get("is_repack", False):
            score += repack_bonus

        # Trusted / blocked release groups
        release_group = metadata.get("release_group", "").upper()
        if preferences:
            trusted_groups = [g.upper() for g in preferences.get("trusted_groups", [])]
            blocked_groups = [g.upper() for g in preferences.get("blocked_groups", [])]
            trusted_bonus = preferences.get("trusted_group_bonus", 5)
        else:
            trusted_groups = [
                "SPARKS",
                "DEFLATE",
                "TOMMY",
                "VYNDROS",
                "SIC",
                "DON",
                "CRUELTY",
                "SCENE",
                "ROVERS",
                "SURCODE",
                "FLUX",
                "NCMT",
            ]
            blocked_groups = []
            trusted_bonus = 5

        if release_group and release_group in blocked_groups:
            return 0.0
        if release_group and release_group in trusted_groups:
            score += trusted_bonus

        # Language, client codec-compatibility, release-age and clamp are
        # identical across library types — shared in LibraryBase.
        return self._finalize_release_score(
            score, metadata, preferences, video_codec, audio_codecs
        )

    def get_naming_schema(self) -> dict[str, Any]:
        """Get the naming schema for movie libraries."""
        return {
            "variables": [
                {
                    "name": "title",
                    "description": "Movie title",
                    "example": "The Matrix",
                },
                {
                    "name": "original_title",
                    "description": "Original title (if different)",
                    "example": "The Matrix",
                },
                {"name": "year", "description": "Release year", "example": "1999"},
                {"name": "tmdb_id", "description": "TMDb ID", "example": "603"},
                {"name": "imdb_id", "description": "IMDb ID", "example": "tt0133093"},
                {
                    "name": "resolution",
                    "description": "Video resolution (from probe)",
                    "example": "1080p",
                },
                {
                    "name": "video_codec",
                    "description": "Video codec (from probe)",
                    "example": "x265",
                },
                {
                    "name": "audio_codec",
                    "description": "Audio codec (from probe)",
                    "example": "AC3",
                },
                {
                    "name": "audio_channels",
                    "description": "Audio channels (from probe)",
                    "example": "5.1",
                },
                {
                    "name": "hdr_format",
                    "description": "HDR format (from probe)",
                    "example": "HDR10",
                },
                {
                    "name": "source",
                    "description": "Release source",
                    "example": "BluRay",
                },
                {
                    "name": "release_group",
                    "description": "Release group",
                    "example": "SPARKS",
                },
                {
                    "name": "edition",
                    "description": "Edition tags",
                    "example": "Extended",
                },
            ],
            "defaults": {
                "folder": "{movie_title} ({movie_year})",
                "file": "{movie_title} ({movie_year})",
            },
            "options": {"replace_illegal_characters": True, "colon_replacement": " -"},
        }

    def get_settings_schema(self) -> dict[str, Any]:
        return {
            "enable_library": {"default": True, "key": "enabled"},
            "library_path": {"default": "/library/movies"},
            "enable_on_demand_downloads": {"default": True},
            "enable_prefetch_downloads": {"default": False},
            "download_rules": {"default": []},
            "on_demand_rules": {"default": []},
        }

    def get_preview_data(self) -> dict[str, Any]:
        return {"title": "The Dark Knight", "year": 2008}

    async def probe_media_file(self, file_path: str) -> dict[str, Any]:
        from streamarr.database import sessionmanager
        from streamarr.libraries.base import structure_probe_data
        from streamarr.services.computing import ComputingService

        try:
            logger.info("Probing movie file: %s", file_path)
            async with sessionmanager.session() as session:
                async with ComputingService(session) as computing_service:
                    raw_ffprobe = await computing_service.probe_media_file(file_path)
            if not raw_ffprobe:
                return {}
            return structure_probe_data(raw_ffprobe)
        except Exception as e:
            logger.error("Error probing %s: %s", file_path, e)
            return {}

    async def suggest_folder_name(
        self,
        media_info: dict[str, Any],
        template: str | None = None,
        tmdb_id: int | None = None,
        imdb_id: str | None = None,
    ) -> str:
        """
        Suggest a folder name for a movie using template or Trash Guide convention.

        Args:
            media_info: Movie metadata (title, year)
            template: Optional template string
            tmdb_id: TMDb ID
            imdb_id: IMDb ID (alternative)

        Returns:
            str: Suggested folder name
        """
        # Add IDs to media_info for template processing
        if tmdb_id:
            media_info = {**media_info, "tmdb_id": tmdb_id}
        if imdb_id:
            media_info = {**media_info, "imdb_id": imdb_id}

        # Use template if provided
        if template:
            return await self._apply_template(
                template, media_info, tmdb_id=tmdb_id, imdb_id=imdb_id
            )

        # Default Trash Guide format
        title = media_info.get("title", "Unknown Movie")
        year = media_info.get("year", "")

        clean_title = self._clean_title(title)

        if year:
            folder = f"{clean_title} ({year})"
        else:
            folder = clean_title

        if tmdb_id:
            folder += f" {{tmdb-{tmdb_id}}}"
        elif imdb_id:
            folder += f" {{imdb-{imdb_id}}}"

        return folder

    async def suggest_file_name(
        self,
        media_info: dict[str, Any],
        template: str | None = None,
        release_metadata: dict[str, Any] | None = None,
        probe_data: dict[str, Any] | None = None,
        edition_tags: str | None = None,
        custom_formats: list[str] | None = None,
        release_group: str | None = None,
    ) -> str:
        """
        Suggest a file name for a movie using template or Trash Guide convention.

        Args:
            media_info: Movie metadata (title, year, tmdb_id)
            template: Optional template string
            release_metadata: Metadata from release title parsing
            probe_data: Technical metadata from probe_media_file()
                        (structured format with video_streams/audio_streams)
            edition_tags: Edition tags (e.g., "Director's Cut", "IMAX")
            custom_formats: Custom format tags
            release_group: Release group name

        Returns:
            str: Suggested file name (without extension)
        """
        from streamarr.libraries.base import extract_naming_metadata

        # Add additional variables to media_info
        enriched_info = {
            **media_info,
            "edition": edition_tags or "",
            "release_group": release_group or "",
        }

        # Derive flat naming metadata from structured probe data
        if probe_data and "video_streams" in probe_data:
            naming_meta = extract_naming_metadata(probe_data)
        elif probe_data:
            # Legacy flat format (backwards compat)
            naming_meta = probe_data
        else:
            naming_meta = {}

        # Merge with release_metadata as fallback
        metadata = {**(release_metadata or {}), **naming_meta}

        if metadata:
            enriched_info.update(
                {
                    "source": metadata.get("source", ""),
                    "resolution": metadata.get("resolution", ""),
                    "audio_codec": metadata.get("audio_codec", ""),
                    "audio_channels": metadata.get("audio_channels", ""),
                    "video_codec": metadata.get("video_codec", ""),
                    "hdr_format": metadata.get("hdr_format", ""),
                }
            )

        # Use template if provided
        if template:
            return await self._apply_template(
                template, enriched_info, probe_data=probe_data
            )

        # Default Trash Guide format
        title = media_info.get("title", "Unknown Movie")
        year = media_info.get("year", "")
        tmdb_id = media_info.get("tmdb_id")

        clean_title = self._clean_title(title)

        parts = [clean_title]

        if year:
            parts.append(f"({year})")

        if tmdb_id:
            parts.append(f"{{tmdb-{tmdb_id}}}")

        # Edition tags
        if edition_tags:
            parts.append(f"{{edition-{edition_tags}}}")

        # Custom formats
        if custom_formats:
            parts.append(f"[{' '.join(custom_formats)}]")

        # Quality (resolution + source)
        quality_parts = []

        # Check for 3D
        if metadata.get("is_3d"):
            quality_parts.append("3D")

        # Source and resolution
        source = metadata.get("source", "").upper()
        resolution = metadata.get("resolution", "")

        if source and resolution:
            quality_parts.append(f"{source}-{resolution}")
        elif resolution:
            quality_parts.append(resolution)
        elif source:
            quality_parts.append(source)

        if quality_parts:
            parts.append(f"[{' '.join(quality_parts)}]")

        # Audio codec and channels
        audio_codec = metadata.get("audio_codec", "")
        audio_channels = metadata.get("audio_channels", "")

        if audio_codec:
            audio_str = audio_codec
            if audio_channels:
                audio_str += f" {audio_channels}"
            parts.append(f"[{audio_str}]")

        # HDR format
        hdr_format = metadata.get("hdr_format", "")
        if hdr_format:
            parts.append(f"[{hdr_format}]")

        # Video codec
        video_codec = metadata.get("video_codec", "")
        if video_codec:
            codec_display = {"h264": "x264", "h265": "x265", "av1": "AV1"}.get(
                video_codec.lower(), video_codec.upper()
            )
            parts.append(f"[{codec_display}]")

        # Release group
        if release_group:
            parts.append(f"-{release_group}")

        return " ".join(parts)

    async def handle_completed_download(
        self,
        *,
        download_context: dict[str, Any],
        files: list[Path],
        db: Any,
    ) -> dict[str, Any]:
        """Import completed movie download into the library."""
        from streamarr.models.media import AvailabilityStatus, MediaFile

        download = download_context["download"]
        media_item = download_context["media_item"]
        _ = download_context.get("release_metadata", {})  # noqa: F841 — used by library copy flow

        # Register files in-place on the rclone mount. Favoriting triggers the
        # library copy separately; non-favorited items stay on the remote.
        files_imported = 0
        files_probed = 0
        for file in files:
            extension = file.suffix
            source_path = str(file)

            # Probe must succeed before we register the file — otherwise the
            # UI gets a ready media_file with no duration/codec info and
            # playback starts on top of missing metadata.
            import asyncio as _asyncio
            probe_data = None
            for attempt in range(4):
                probe_data = await self.probe_media_file(source_path)
                if probe_data and extract_naming_metadata(probe_data).get("duration"):
                    break
                await _asyncio.sleep(2 ** attempt)
            naming_meta = extract_naming_metadata(probe_data) if probe_data else {}

            logger.info("Registered movie file from rclone: %s", source_path)

            media_file = MediaFile(
                guid=uuid.uuid4(),
                media_item_guid=media_item.guid,
                file_path=source_path,
                file_name=file.name,
                file_size=file.stat().st_size,
                duration=naming_meta.get("duration"),
                width=naming_meta.get("width"),
                height=naming_meta.get("height"),
                codec=naming_meta.get("video_codec"),
                bitrate=naming_meta.get("bitrate"),
                quality=naming_meta.get("resolution"),
                format=extension.lstrip("."),
                probe_data=json.dumps(probe_data) if probe_data else None,
            )
            db.add(media_file)
            await db.commit()
            files_imported += 1
            if probe_data:
                files_probed += 1

        if files_probed > 0:
            media_item.availability_status = AvailabilityStatus.AVAILABLE
            await db.commit()
        else:
            logger.error(
                "Movie %s: %s file(s) imported but none were successfully probed — treating as failed import",
                media_item.title, files_imported,
            )
            from sqlalchemy import select

            # Only clean up DB rows — files live on the rclone mount.
            result = await db.execute(
                select(MediaFile).where(
                    MediaFile.media_item_guid == media_item.guid
                )
            )
            for mf in result.scalars().all():
                await db.delete(mf)
            await db.commit()
            return {"success": False, "error": "Probe failed for all files"}

        try:
            from streamarr.services.redis_event import get_redis_event_service

            redis_service = get_redis_event_service()
            await redis_service.publish_media_item_updated(
                media_item_id=media_item.guid,
                update_type="media_available",
                data={"files_imported": files_imported},
            )
        except Exception as e:
            logger.warning("Failed to publish media_available event: %s", e)

        return {
            "success": True,
            "files_imported": files_imported,
            "movie_title": media_item.title,
        }

    async def promote_to_library(self, media_file, db) -> dict[str, Any]:
        """Copy an already-registered rclone-backed file into /library.

        Called when a movie gets favorited so the file survives remote-side
        retention. No-op if the media_file already lives under /library.
        """
        from streamarr.models.media import MediaItem

        src = Path(media_file.file_path)
        library_path = await self.get_default_path()
        if str(src).startswith(library_path):
            return {"success": True, "already_in_library": True}
        if not src.exists():
            return {"success": False, "error": f"Source missing: {src}"}

        media_item = await db.get(MediaItem, media_file.media_item_guid)
        if not media_item:
            return {"success": False, "error": "Media item not found"}

        await db.refresh(media_item, attribute_names=["external_ids"])
        tmdb_id = imdb_id = None
        for ext in media_item.external_ids:
            if ext.provider == "tmdb":
                tmdb_id = ext.external_id
            elif ext.provider == "imdb":
                imdb_id = ext.external_id

        movie_info = {
            "title": media_item.title,
            "year": media_item.release_date.year if media_item.release_date else None,
            "tmdb_id": tmdb_id, "imdb_id": imdb_id,
        }
        movie_folder = await self.suggest_folder_name(
            media_info=movie_info, tmdb_id=tmdb_id,
        )

        folder = safe_library_child_path(library_path, movie_folder)
        if folder is None:
            logger.error(
                "promote_to_library: rejected path-escape attempt %s (library=%s)",
                movie_folder, library_path,
            )
            return {"success": False, "error": "Refused to write outside library root"}
        folder.mkdir(parents=True, exist_ok=True)

        probe_data = json.loads(media_file.probe_data) if media_file.probe_data else None
        new_name = await self.suggest_file_name(
            media_info=movie_info, probe_data=probe_data, release_group=None,
        )
        dest = safe_library_child_path(folder, f"{new_name}{src.suffix}")
        if dest is None:
            logger.error(
                "promote_to_library: rejected file path-escape %s (library=%s)",
                new_name, library_path,
            )
            return {"success": False, "error": "Refused to write outside library root"}
        await asyncio.to_thread(shutil.copy2, str(src), str(dest))
        logger.info("Promoted movie to library: %s -> %s", src, dest)

        media_file.file_path = str(dest)
        media_file.file_name = dest.name
        await db.commit()
        return {"success": True, "file_path": str(dest)}
