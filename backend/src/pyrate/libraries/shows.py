"""Show/Series library plugin."""

import asyncio
import json
import logging
import os
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from pyrate.libraries.base import LibraryBase, extract_naming_metadata
from pyrate.libraries.video_helpers import (
    VIDEO_EXTENSIONS,
    iter_video_files,
    library_video_stats,
    safe_library_child_path,
    validate_library_path,
    video_file_info,
)
from pyrate.parsers.release_parser import ReleaseParser

logger = logging.getLogger(__name__)


class ShowLibraryPlugin(LibraryBase):
    """Plugin for managing TV show/series libraries."""

    def get_name(self) -> str:
        return "Show Library"

    def get_library_type(self) -> str:
        return "SHOWS"

    def get_media_item_types(self) -> list[dict[str, Any]]:
        return [
            {"name": "SHOWS", "label": "Show", "parent_type": None},
            {"name": "SEASONS", "label": "Season", "parent_type": "SHOWS"},
            {"name": "EPISODES", "label": "Episode", "parent_type": "SEASONS"},
        ]

    async def get_default_path(self) -> str:
        return "/library/shows"

    async def validate_path(self, path: str) -> bool:
        """Validate show library path."""
        return validate_library_path(path)

    async def get_library_stats(self, path: str) -> dict[str, Any]:
        """Get statistics about the show library."""
        return library_video_stats(
            path,
            include_top_level_dir_count=True,
            top_level_dir_count_key="show_count",
        )

    # ==================== Media-Specific Operations ====================

    def _get_video_extensions(self) -> set[str]:
        """Get supported video extensions for shows."""
        return set(VIDEO_EXTENSIONS)

    async def get_supported_extensions(self) -> list[str]:
        """Get list of supported file extensions for shows."""
        return list(self._get_video_extensions())

    async def scan_library(self, path: str) -> list[dict[str, Any]]:
        """
        Scan library path for show episode files.

        Structure expected: /library/shows/Show Name/Season 01/S01E01.mkv

        Args:
            path: The library path to scan

        Returns:
            list[dict]: List of discovered episode files with metadata
        """
        discovered = []

        try:
            path_obj = Path(path)
            if not path_obj.exists():
                logger.warning("Library path does not exist: %s", path)
                return discovered

            for file_path in iter_video_files(path_obj):
                file_info = video_file_info(file_path)

                # Extract metadata from filename and path structure
                metadata = await self.extract_metadata_from_filename(file_path.name)

                # Try to extract show name from directory structure
                # Expected: /library/shows/Show Name/Season 01/episode.mkv
                parts = file_path.parts
                if len(parts) >= 3:
                    # Get show name (parent's parent directory)
                    show_name = parts[-3] if len(parts) >= 3 else None
                    if show_name and show_name != "shows":
                        metadata["show_name"] = show_name

                file_info.update(metadata)
                discovered.append(file_info)

            logger.info("Found %s episode files in %s", len(discovered), path)

        except Exception as e:
            logger.error("Error scanning show library %s: %s", path, e)

        return discovered

    async def extract_metadata_from_filename(self, filename: str) -> dict[str, Any]:
        """
        Extract metadata from episode filename.

        Supports patterns like:
        - S01E01.mkv
        - Show Name - S01E01 - Episode Title.mkv
        - Show.Name.1x01.Episode.Title.mkv
        - Show Name - 1x01 - Episode Title.mkv

        Args:
            filename: The filename to parse

        Returns:
            dict: Extracted metadata (show, season, episode, title, etc.)
        """
        metadata: dict[str, Any] = {}

        # Remove extension
        name = Path(filename).stem

        # Try standard SxxExx pattern
        se_pattern = r"[Ss](\d{1,2})[Ee](\d{1,2})"
        se_match = re.search(se_pattern, name)

        if se_match:
            metadata["season"] = int(se_match.group(1))
            metadata["episode"] = int(se_match.group(2))
        else:
            # Try alternative 1x01 pattern
            alt_pattern = r"(\d{1,2})x(\d{1,2})"
            alt_match = re.search(alt_pattern, name)
            if alt_match:
                metadata["season"] = int(alt_match.group(1))
                metadata["episode"] = int(alt_match.group(2))

        # Extract quality
        if "2160p" in name or "4K" in name:
            metadata["quality"] = "2160p"
        elif "1080p" in name:
            metadata["quality"] = "1080p"
        elif "720p" in name:
            metadata["quality"] = "720p"
        elif "480p" in name:
            metadata["quality"] = "480p"

        # Extract source
        if "BluRay" in name or "Blu-Ray" in name:
            metadata["source"] = "BluRay"
        elif "WEB-DL" in name or "WEBRip" in name:
            metadata["source"] = "WEB"
        elif "HDTV" in name:
            metadata["source"] = "HDTV"

        return metadata

    async def format_file_path(
        self, media_info: dict[str, Any], library_path: str
    ) -> str:
        """
        Generate the proper file path for an episode within library.

        Format: /library/shows/Show Name/Season 01/

        Args:
            media_info: Media metadata (show, season, episode, etc.)
            library_path: Base library path

        Returns:
            str: Formatted path for the episode file
        """
        show_name = media_info.get("show_name", "Unknown Show")
        season_number = media_info.get("season", 1)

        # Sanitize show name
        safe_show = "".join(
            c for c in show_name if c.isalnum() or c in (" ", "-", "_")
        ).strip()

        # Format season folder
        season_folder = f"Season {season_number:02d}"

        return os.path.join(library_path, safe_show, season_folder)

    async def validate_media_file(self, file_path: str) -> bool:
        """
        Validate that a file is a valid episode file.

        Args:
            file_path: Path to the file to validate

        Returns:
            bool: True if file is valid episode file
        """
        try:
            path = Path(file_path)
            if not path.is_file():
                return False

            # Check extension
            if path.suffix.lower() not in self._get_video_extensions():
                return False

            # Check if filename contains episode identifier
            se_pattern = r"[Ss]\d{1,2}[Ee]\d{1,2}|\d{1,2}x\d{1,2}"
            if not re.search(se_pattern, path.name):
                logger.warning("File %s doesn't match episode naming pattern", file_path)
                return False

            # Check minimum file size (avoid samples)
            # Minimum 20MB for episodes
            if path.stat().st_size < 20 * 1024 * 1024:
                logger.warning("File %s is too small to be an episode", file_path)
                return False

            return True

        except Exception as e:
            logger.error("Error validating episode file %s: %s", file_path, e)
            return False

    async def get_metadata_provider(self) -> str | None:
        """Get the preferred metadata provider for shows."""
        return "tmdb"  # TMDB also provides TV show data

    async def match_media(self, file_info: dict[str, Any]) -> dict[str, Any] | None:
        """
        Match an episode file to TMDB/TVDB metadata.

        This is a placeholder - actual implementation would call TMDB API.

        Args:
            file_info: Information about the episode file

        Returns:
            dict | None: Matched episode metadata or None if no match found
        """
        # Metadata matching is not wired to a provider from this hook; a None
        # result means "no automatic match" and callers handle it. (This path
        # is currently unused — enrichment goes through the metadata services.)
        return None

    # ==================== Release Metadata Extraction ====================

    async def extract_release_metadata(self, release_title: str) -> dict[str, Any]:
        """
        Extract metadata from a TV show episode release title.

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
            metadata["quality"] = resolution

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
            metadata["audio_codec"] = audio_codecs[0]

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
        Calculate a quality score for a TV episode release.

        Score ranges from 0-100, with higher scores indicating better quality.
        For TV shows, we typically prefer WEB-DL over BluRay due to availability.

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
            if resolution == "2160p":
                score += res_weights.get("2160p", 25)
            elif resolution == "1080p":
                score += res_weights.get("1080p", 22)
            elif resolution == "720p":
                score += res_weights.get("720p", 15)
            elif resolution == "480p":
                score += res_weights.get("480p", 8)
        else:
            if resolution == "2160p":
                score += 25
            elif resolution == "1080p":
                score += 22
            elif resolution == "720p":
                score += 15
            elif resolution == "480p":
                score += 8

        # Source scoring (0-20 points)
        # For TV shows, WEB-DL is often preferred as it's available sooner
        source = metadata.get("source", "").lower()
        if preferences:
            src_weights = preferences.get("source", {})
            if source == "web-dl":
                score += src_weights.get("web-dl", 20)
            elif source == "webrip":
                score += src_weights.get("webrip", 18)
            elif source == "bluray":
                score += src_weights.get("bluray", 16)
            elif source == "remux":
                score += src_weights.get("remux", 16)
            elif source == "hdtv":
                score += src_weights.get("hdtv", 12)
            elif source == "dvd":
                score += src_weights.get("dvd", 5)
            elif source == "screener":
                score += src_weights.get("screener", 2)
            elif source in ("cam", "telesync", "telecine"):
                score += src_weights.get("cam", 1)
        else:
            if source == "web-dl":
                score += 20
            elif source == "webrip":
                score += 18
            elif source == "bluray" or source == "remux":
                score += 16
            elif source == "hdtv":
                score += 12
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
                score += codec_weights.get("h264", 13)
            elif video_codec in ["xvid", "divx"]:
                score += codec_weights.get(video_codec, 5)
        else:
            if video_codec == "h265" or video_codec == "av1":
                score += 15
            elif video_codec == "h264":
                score += 13
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
                score += audio_weights.get("eac3", 7)
            elif "ac3" in audio_codecs:
                score += audio_weights.get("ac3", 7)
            elif "aac" in audio_codecs:
                score += audio_weights.get("aac", 5)
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
                score += 7
            elif "aac" in audio_codecs:
                score += 5

        # Special features bonus (0-10 points)
        hdr_bonus = preferences.get("hdr_bonus", 5) if preferences else 5
        dv_bonus = preferences.get("dolby_vision_bonus", 5) if preferences else 5
        if metadata.get("is_hdr", False):
            score += hdr_bonus
        if metadata.get("is_dolby_vision", False):
            score += dv_bonus

        # PROPER/REPACK bonus (0-5 points)
        proper_bonus = preferences.get("proper_bonus", 5) if preferences else 5
        repack_bonus = preferences.get("repack_bonus", 3) if preferences else 3
        if metadata.get("is_proper", False):
            score += proper_bonus
        if metadata.get("is_repack", False):
            score += repack_bonus

        # Trusted / blocked release groups for TV
        release_group = metadata.get("release_group", "").upper()
        if preferences:
            trusted_groups = [g.upper() for g in preferences.get("trusted_groups", [])]
            blocked_groups = [g.upper() for g in preferences.get("blocked_groups", [])]
            trusted_bonus = preferences.get("trusted_group_bonus", 5)
        else:
            trusted_groups = [
                "DEFLATE",
                "TOMMY",
                "FLUX",
                "NTB",
                "CAKES",
                "WELP",
                "SIGMA",
                "BTN",
                "CRUELTY",
                "HONE",
                "CMRG",
                "TMSF",
                "AVTOMAT",
                "ISSEYMIYAKE",
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
        """Get the naming schema for TV show libraries."""
        return {
            "variables": [
                {
                    "name": "show_title",
                    "description": "Show title",
                    "example": "The Walking Dead",
                },
                {
                    "name": "original_title",
                    "description": "Original title (if different)",
                    "example": "The Walking Dead",
                },
                {"name": "year", "description": "First air year", "example": "2010"},
                {"name": "tvdb_id", "description": "TVDB ID", "example": "153021"},
                {"name": "tmdb_id", "description": "TMDb ID", "example": "1402"},
                {"name": "imdb_id", "description": "IMDb ID", "example": "tt1520211"},
                {"name": "season", "description": "Season number", "example": "1"},
                {
                    "name": "season_2",
                    "description": "Season number (zero-padded)",
                    "example": "01",
                },
                {"name": "episode", "description": "Episode number", "example": "1"},
                {
                    "name": "episode_2",
                    "description": "Episode number (zero-padded)",
                    "example": "01",
                },
                {
                    "name": "episode_title",
                    "description": "Episode title",
                    "example": "Days Gone Bye",
                },
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
                    "example": "EAC3",
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
                    "example": "WEB-DL",
                },
                {
                    "name": "release_group",
                    "description": "Release group",
                    "example": "DEFLATE",
                },
            ],
            "defaults": {
                "series_folder": "{series_title} ({series_year})",
                "season_folder": "Season {season_number_2}",
                "episode_file": "{series_title} - S{season_number_2}E{episode_number_2} - {episode_title}",
            },
            "options": {
                "multi_episode_style": "extend",
                "replace_illegal_characters": True,
                "colon_replacement": " -",
            },
        }

    def get_settings_schema(self) -> dict[str, Any]:
        return {
            "enable_library": {"default": True, "key": "enabled"},
            "library_path": {"default": "/library/shows"},
            "enable_on_demand_downloads": {"default": True},
            "enable_prefetch_downloads": {"default": False},
            "hide_season_zero": {"default": False},
            "download_rules": {"default": []},
            "on_demand_rules": {"default": []},
        }

    def get_preview_data(self) -> dict[str, Any]:
        return {
            "title": "The Walking Dead",
            "year": 2010,
            "season_number": 1,
            "episode_number": 1,
            "episode_title": "Days Gone Bye",
        }

    async def probe_media_file(self, file_path: str) -> dict[str, Any]:
        from pyrate.database import sessionmanager
        from pyrate.libraries.base import structure_probe_data
        from pyrate.services.computing import ComputingService

        try:
            logger.info("Probing episode file: %s", file_path)
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
        tmdb_id: int | None = None,
        imdb_id: str | None = None,
    ) -> str:
        """
        Suggest a folder name for a show following Trash Guide convention.

        Format: {Show CleanTitle} ({Release Year}) {tmdb-{TmdbId}}
        Example: The Series Title! (2010) {tmdb-12345}

        Args:
            media_info: Show metadata (title, year, tmdb_id, tvdb_id)
            tmdb_id: TMDb ID (preferred)
            imdb_id: IMDb ID (alternative)

        Returns:
            str: Suggested folder name
        """
        title = media_info.get("title", "Unknown Show")
        year = media_info.get("year", "")

        # Prefer tmdb_id parameter, then from media_info
        if not tmdb_id:
            tmdb_id = media_info.get("tmdb_id")

        clean_title = self._clean_title(title)

        if year:
            folder = f"{clean_title} ({year})"
        else:
            folder = clean_title

        # Use TMDb ID following Plex naming scheme from Trash Guide
        if tmdb_id:
            folder += f" {{tmdb-{tmdb_id}}}"
        elif imdb_id:
            # Fallback to IMDb if no TMDb ID available
            folder += f" {{imdb-{imdb_id}}}"

        return folder

        return folder

    async def suggest_file_name(
        self,
        media_info: dict[str, Any],
        release_metadata: dict[str, Any] | None = None,
        probe_data: dict[str, Any] | None = None,
        edition_tags: str | None = None,
        custom_formats: list[str] | None = None,
        release_group: str | None = None,
    ) -> str:
        """
        Suggest a file name for an episode following Trash Guide convention.

        Format: {Show CleanTitle} - S{season:00}E{episode:00} - {Episode CleanTitle}
                {[Edition]}{[Custom Formats]}{[Quality Full]}
                {[Audio Codec Channels]}{[HDR]}{[Video Codec]}{-Release Group}

        Example: The Series Title! - S01E01 - Episode Title [AMZN WEBDL-1080p Proper][DV HDR10][DTS 5.1][x264]-RlsGrp

        Args:
            media_info: Episode metadata (show_title, season, episode, episode_title)
            release_metadata: Metadata from release title parsing
            probe_data: Technical metadata from probe_media_file()
                        (structured format with video_streams/audio_streams)
            edition_tags: Edition tags (e.g., "PROPER", "REPACK")
            custom_formats: Custom format tags
            release_group: Release group name

        Returns:
            str: Suggested file name (without extension)
        """
        from pyrate.libraries.base import extract_naming_metadata

        show_title = media_info.get("show_title", "Unknown Show")
        season = media_info.get("season", 1)
        episode = media_info.get("episode", 1)
        episode_title = media_info.get("episode_title", "")

        clean_show_title = self._clean_title(show_title)

        # Base: Show Title - S01E01
        parts = [f"{clean_show_title} - S{season:02d}E{episode:02d}"]

        # Episode title if available
        if episode_title:
            clean_episode_title = self._clean_title(episode_title)
            parts.append(f"- {clean_episode_title}")

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

        # Extract metadata fields
        source = metadata.get("source", "")
        resolution = metadata.get("resolution", "")
        audio_codec = metadata.get("audio_codec", "")
        audio_channels = metadata.get("audio_channels", "")
        hdr_format = metadata.get("hdr_format", "")
        video_codec = metadata.get("video_codec", "")

        # Build quality tag: [SOURCE RESOLUTION] or [SOURCE-RESOLUTION]
        quality_tag = self._format_quality_tag(source, resolution)
        if quality_tag:
            # Insert edition before quality if present
            if edition_tags:
                parts.append(
                    f"[{source} {resolution} {edition_tags}]"
                    if source and resolution
                    else f"[{edition_tags}]"
                )
                quality_tag = ""  # Already added with edition
            else:
                parts.append(quality_tag)
        elif edition_tags:
            parts.append(self._format_edition_tag(edition_tags))

        # Custom formats
        custom_format_tag = self._format_custom_formats_tag(custom_formats)
        if custom_format_tag:
            parts.append(custom_format_tag)

        # HDR tag
        hdr_tag = self._format_hdr_tag(hdr_format)
        if hdr_tag:
            parts.append(hdr_tag)

        # Audio tag
        audio_tag = self._format_audio_tag(audio_codec, audio_channels)
        if audio_tag:
            parts.append(audio_tag)

        # Video codec tag
        video_tag = self._format_video_codec_tag(video_codec)
        if video_tag:
            parts.append(video_tag)

        # Release group
        rls_tag = self._format_release_group_tag(release_group)
        if rls_tag:
            parts.append(rls_tag)

        return " ".join(parts)

    async def handle_completed_download(
        self,
        *,
        download_context: dict[str, Any],
        files: list[Path],
        db: Any,
    ) -> dict[str, Any]:
        """Import completed episode download into the library."""
        from pyrate.models.media import AvailabilityStatus, MediaFile, MediaItem

        download = download_context["download"]
        episode = download_context["media_item"]
        _ = download_context.get("release_metadata", {})  # noqa: F841 — used by library copy flow

        if not episode.parent_guid:
            logger.error("Episode %s has no parent (season)", episode.guid)
            return {"success": False, "error": "Episode has no season"}

        # Resolve season/show for the return payload (used by downstream events)
        season = await db.get(MediaItem, episode.parent_guid)
        show = await db.get(MediaItem, season.parent_guid) if season and season.parent_guid else None
        season_number = season.sequence_number if season else None
        episode_number = episode.sequence_number

        # Register the file in-place on the rclone mount rather than copying it
        # into /library. Favoriting an item later triggers a library copy
        # separately; non-favorited items stay on the remote and are evicted
        # by retention.
        files_imported = 0
        files_probed = 0
        for file in files:
            extension = file.suffix
            source_path = str(file)

            # Probe must succeed before we register the file — otherwise the
            # UI gets a ready media_file with no duration/codec info and
            # playback starts on top of missing metadata. Retry a few times:
            # rclone can still be populating the VFS on the first attempt.
            import asyncio as _asyncio
            probe_data = None
            for attempt in range(4):
                probe_data = await self.probe_media_file(source_path)
                if probe_data and extract_naming_metadata(probe_data).get("duration"):
                    break
                await _asyncio.sleep(2 ** attempt)
            naming_meta = extract_naming_metadata(probe_data) if probe_data else {}

            logger.info("Registered episode file from rclone: %s", source_path)

            media_file = MediaFile(
                guid=uuid.uuid4(),
                media_item_guid=episode.guid,
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

            # Extract and store audio fingerprint for intro detection
            if probe_data:
                try:
                    from pyrate.services.chromaprint import ChromaprintService

                    chromaprint_service = ChromaprintService(db)
                    fp = await chromaprint_service.extract_and_store_fingerprint(
                        media_file.guid
                    )
                    if fp:
                        logger.info(
                            "Stored audio fingerprint for episode %s",
                            episode.title,
                        )
                    else:
                        logger.warning(
                            "Could not extract audio fingerprint for episode %s",
                            episode.title,
                        )
                except Exception as e:
                    logger.warning(
                        "Audio fingerprint extraction failed for %s: %s",
                        episode.title,
                        e,
                    )

        if files_probed > 0:
            episode.availability_status = AvailabilityStatus.AVAILABLE
            await db.commit()
        else:
            logger.error(
                "Episode %s: %s file(s) imported but "
                "none were successfully probed — treating as failed import",
                episode.title, files_imported,
            )
            from sqlalchemy import select

            # Only clean up DB rows here — the files live on the rclone mount
            # and shouldn't be deleted on probe failure. Retention removes them.
            result = await db.execute(
                select(MediaFile).where(
                    MediaFile.media_item_guid == episode.guid
                )
            )
            for mf in result.scalars().all():
                await db.delete(mf)
            await db.commit()
            return {"success": False, "error": "Probe failed for all files"}

        try:
            from pyrate.services.redis_event import get_redis_event_service

            redis_service = get_redis_event_service()
            await redis_service.publish_media_item_updated(
                media_item_id=episode.guid,
                update_type="media_available",
                data={"files_imported": files_imported},
            )
        except Exception as e:
            logger.warning("Failed to publish media_available event: %s", e)

        return {
            "success": True,
            "files_imported": files_imported,
            "show_title": show.title if show else None,
            "season_number": season_number,
            "episode_number": episode_number,
        }

    async def promote_to_library(self, media_file, db) -> dict[str, Any]:
        """Copy an already-registered rclone-backed file into /library.

        Called when an episode gets favorited so the file survives remote-side
        retention. No-op if the media_file already lives under /library.
        """
        from pyrate.models.media import MediaItem

        src = Path(media_file.file_path)
        library_path = await self.get_default_path()
        if str(src).startswith(library_path):
            return {"success": True, "already_in_library": True}
        if not src.exists():
            return {"success": False, "error": f"Source missing: {src}"}

        episode = await db.get(MediaItem, media_file.media_item_guid)
        if not episode or not episode.parent_guid:
            return {"success": False, "error": "Episode has no season"}
        season = await db.get(MediaItem, episode.parent_guid)
        if not season or not season.parent_guid:
            return {"success": False, "error": "Season has no show"}
        show = await db.get(MediaItem, season.parent_guid)
        if not show:
            return {"success": False, "error": "Show not found"}

        await db.refresh(show, attribute_names=["external_ids"])
        tvdb_id = tmdb_id = imdb_id = None
        for ext in show.external_ids:
            if ext.provider == "tvdb":
                tvdb_id = ext.external_id
            elif ext.provider == "tmdb":
                tmdb_id = ext.external_id
            elif ext.provider == "imdb":
                imdb_id = ext.external_id

        show_folder = await self.suggest_folder_name(
            media_info={
                "title": show.title,
                "year": show.release_date.year if show.release_date else None,
                "tvdb_id": tvdb_id, "tmdb_id": tmdb_id, "imdb_id": imdb_id,
            },
            tmdb_id=tmdb_id, imdb_id=imdb_id,
        )
        season_number = season.sequence_number or 1
        season_folder = safe_library_child_path(
            library_path,
            show_folder,
            f"Season {season_number:02d}",
        )
        if season_folder is None:
            logger.error(
                "promote_to_library: rejected path-escape attempt %s (library=%s)",
                show_folder,
                library_path,
            )
            return {"success": False, "error": "Refused to write outside library root"}
        season_folder.mkdir(parents=True, exist_ok=True)

        probe_data = json.loads(media_file.probe_data) if media_file.probe_data else None
        new_name = await self.suggest_file_name(
            media_info={
                "show_title": show.title,
                "season": season_number,
                "episode": episode.sequence_number or 1,
                "episode_title": episode.title or f"Episode {episode.sequence_number or 1}",
            },
            probe_data=probe_data,
            release_group=None,
        )
        dest = safe_library_child_path(season_folder, f"{new_name}{src.suffix}")
        if dest is None:
            logger.error(
                "promote_to_library: rejected file path-escape %s (library=%s)",
                new_name,
                library_path,
            )
            return {"success": False, "error": "Refused to write outside library root"}
        await asyncio.to_thread(shutil.copy2, str(src), str(dest))
        logger.info("Promoted episode to library: %s -> %s", src, dest)

        media_file.file_path = str(dest)
        media_file.file_name = dest.name
        await db.commit()
        return {"success": True, "file_path": str(dest)}
