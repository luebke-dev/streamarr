"""
Base class for pyrate library plugins.

This module defines the LibraryBase abstract base class for library management,
extracted from the former LibraryPlugin in pyrate.plugins.base.
"""

import logging
import re
from abc import ABC, abstractmethod
from typing import Any, ClassVar

logger = logging.getLogger(__name__)


# ==================== Shared Probe Data Utilities ====================

# Canonical video codec mapping (ffprobe codec_name → display name)
VIDEO_CODEC_MAP = {
    "hevc": "h265",
    "h264": "h264",
    "av1": "av1",
    "vc1": "vc1",
    "mpeg2video": "mpeg2",
    "vp9": "vp9",
}

# Canonical audio codec mapping (ffprobe codec_name → display name)
AUDIO_CODEC_MAP = {
    "aac": "AAC",
    "ac3": "AC3",
    "eac3": "EAC3",
    "dts": "DTS",
    "truehd": "TrueHD",
    "flac": "FLAC",
    "opus": "Opus",
    "vorbis": "Vorbis",
}


def structure_probe_data(raw_ffprobe: dict) -> dict:
    """Structure raw ffprobe JSON output into the canonical probe data format.

    This is the single canonical format for probe_data stored in the database.
    All code paths (plugins, worker tasks) should use this function to produce
    a consistent structure.

    Args:
        raw_ffprobe: Raw JSON output from ``ffprobe -print_format json
                     -show_format -show_streams``

    Returns:
        dict with keys:
            - format: format metadata from ffprobe
            - video_streams: list of structured video stream dicts
            - audio_streams: list of structured audio stream dicts
            - subtitle_streams: list of structured subtitle stream dicts
    """
    structured = {
        "format": raw_ffprobe.get("format", {}),
        "video_streams": [],
        "audio_streams": [],
        "subtitle_streams": [],
    }

    for stream in raw_ffprobe.get("streams", []):
        codec_type = stream.get("codec_type")
        tags = stream.get("tags", {})

        base_info = {
            "index": stream.get("index"),
            "codec_name": stream.get("codec_name"),
            "codec_long_name": stream.get("codec_long_name"),
            "language": tags.get("language", tags.get("LANGUAGE")),
            "title": tags.get("title", tags.get("TITLE")),
            "default": stream.get("disposition", {}).get("default", 0) == 1,
            "forced": stream.get("disposition", {}).get("forced", 0) == 1,
        }

        if codec_type == "video":
            base_info.update({
                "width": stream.get("width"),
                "height": stream.get("height"),
                "bit_rate": stream.get("bit_rate"),
                "frame_rate": stream.get("r_frame_rate"),
                "pix_fmt": stream.get("pix_fmt"),
                "color_transfer": stream.get("color_transfer"),
                "color_space": stream.get("color_space"),
                "side_data_list": stream.get("side_data_list", []),
            })
            structured["video_streams"].append(base_info)

        elif codec_type == "audio":
            base_info.update({
                "channels": stream.get("channels"),
                "channel_layout": stream.get("channel_layout"),
                "sample_rate": stream.get("sample_rate"),
                "bit_rate": stream.get("bit_rate"),
            })
            structured["audio_streams"].append(base_info)

        elif codec_type == "subtitle":
            structured["subtitle_streams"].append(base_info)

    logger.debug(
        "Structured probe data: %d video, %d audio, %d subtitle streams",
        len(structured["video_streams"]),
        len(structured["audio_streams"]),
        len(structured["subtitle_streams"]),
    )
    return structured


def extract_naming_metadata(structured_probe: dict) -> dict[str, Any]:
    """Extract flat naming metadata from structured probe data.

    This produces the flat keys (``resolution``, ``video_codec``,
    ``audio_codec``, ``audio_channels``, ``hdr_format``, ``duration``,
    ``bitrate``, ``width``, ``height``, ``container``) that
    ``suggest_file_name`` and ``_apply_template`` expect.

    Args:
        structured_probe: Probe data in the canonical structured format
                          (as returned by :func:`structure_probe_data`).

    Returns:
        Flat dict with naming-relevant metadata.
    """
    metadata: dict[str, Any] = {}

    video_streams = structured_probe.get("video_streams", [])
    if video_streams:
        video = video_streams[0]
        width = video.get("width", 0)
        height = video.get("height", 0)
        metadata["width"] = width
        metadata["height"] = height

        # Resolution label — use width as primary indicator for widescreen content
        # (e.g. 1920x800 Cinemascope is 1080p, not 720p)
        if width >= 3840 or height >= 2160:
            metadata["resolution"] = "2160p"
        elif width >= 1920 or height >= 1080:
            metadata["resolution"] = "1080p"
        elif width >= 1280 or height >= 720:
            metadata["resolution"] = "720p"
        elif height >= 576:
            metadata["resolution"] = "576p"
        elif height >= 480:
            metadata["resolution"] = "480p"
        else:
            metadata["resolution"] = f"{height}p" if height else ""

        # Video codec
        codec_name = (video.get("codec_name") or "").lower()
        metadata["video_codec"] = VIDEO_CODEC_MAP.get(codec_name, codec_name)

        # HDR metadata
        color_transfer = (video.get("color_transfer") or "").lower()
        if "smpte2084" in color_transfer or "pq" in color_transfer:
            metadata["hdr_format"] = "HDR10"
        elif "arib-std-b67" in color_transfer or "hlg" in color_transfer:
            metadata["hdr_format"] = "HLG"

        # Check for Dolby Vision in side data
        for data in video.get("side_data_list", []):
            if "DOVI" in str(data) or "Dolby Vision" in str(data):
                metadata["hdr_format"] = "DV"
                break

        # Video bitrate
        if video.get("bit_rate"):
            metadata["video_bitrate"] = int(video["bit_rate"]) // 1000

    # Audio
    audio_streams = structured_probe.get("audio_streams", [])
    if audio_streams:
        audio = audio_streams[0]
        codec_name = (audio.get("codec_name") or "").lower()
        metadata["audio_codec"] = AUDIO_CODEC_MAP.get(codec_name, codec_name.upper())

        channels = audio.get("channels", 0)
        channel_layout = audio.get("channel_layout") or ""

        if "7.1" in channel_layout or channels == 8:
            metadata["audio_channels"] = "7.1"
        elif "5.1" in channel_layout or channels == 6:
            metadata["audio_channels"] = "5.1"
        elif channels == 2:
            metadata["audio_channels"] = "2.0"
        elif channels == 1:
            metadata["audio_channels"] = "1.0"
        else:
            metadata["audio_channels"] = f"{channels}.0" if channels else ""

        # Check for Atmos
        if "atmos" in str(audio).lower():
            metadata["audio_codec"] = "TrueHD Atmos"

    # Format info
    format_info = structured_probe.get("format", {})
    if format_info.get("duration"):
        metadata["duration"] = float(format_info["duration"])
    if format_info.get("bit_rate"):
        metadata["bitrate"] = int(format_info["bit_rate"]) // 1000

    # Container format
    format_name = format_info.get("format_name", "")
    if "matroska" in format_name:
        metadata["container"] = "mkv"
    elif "mp4" in format_name:
        metadata["container"] = "mp4"
    else:
        metadata["container"] = format_name.split(",")[0] if format_name else "unknown"

    logger.debug(
        "Extracted naming metadata: resolution=%s codec=%s container=%s duration=%.1fs",
        metadata.get("resolution", "?"),
        metadata.get("video_codec", "?"),
        metadata.get("container", "?"),
        metadata.get("duration", 0),
    )
    return metadata


class LibraryBase(ABC):
    """
    Abstract base class for library management.

    Library classes handle storage, organization, and media-specific operations
    for specific content types (movies, shows, games, music, etc.).

    Unlike the old LibraryPlugin, this class does NOT inherit from PluginBase
    and has no manifest parameter.
    """

    def __init__(self):
        """Initialize the library."""
        pass

    async def setup(self) -> None:  # noqa: B027
        """
        Initialize the library.

        Override this method to perform any setup tasks required
        before the library can be used. The default implementation
        does nothing.
        """
        pass

    async def close(self) -> None:  # noqa: B027
        """
        Clean up library resources.

        Override this method to perform cleanup tasks such as
        closing HTTP clients or database connections. The default
        implementation does nothing.
        """
        pass

    def get_name(self) -> str:
        """
        Get the library name.

        Returns the library type for backward compatibility.

        Returns:
            str: A human-readable name for the library
        """
        return self.get_library_type()

    @abstractmethod
    def get_library_type(self) -> str:
        """
        Get the library type this class handles.

        Returns:
            str: Library type (e.g., 'MOVIES', 'SHOWS', 'GAMES')
        """
        pass

    def get_media_item_types(self) -> list[dict[str, Any]]:
        """
        Get the media item types this library provides.

        Each library class declares what types of media items it manages.
        For simple libraries (movies, books), this is a single type.
        For hierarchical libraries (shows, music), this includes all levels.

        Returns a list of type definitions. Each definition is a dict with:
            - name: Type identifier (uppercase, used as enum value and in DB)
            - label: Human-readable singular name
            - parent_type: Name of the parent type (None for root/top-level types)

        Default implementation returns a single type matching the library type.
        """
        library_type = self.get_library_type()
        return [
            {
                "name": library_type,
                "label": library_type.title(),
                "parent_type": None,
            }
        ]

    @abstractmethod
    async def get_default_path(self) -> str:
        """
        Get the default library path for this content type.

        Returns:
            str: Default path (e.g., '/library/movies')
        """
        pass

    @abstractmethod
    async def validate_path(self, path: str) -> bool:
        """
        Validate that a library path is accessible and properly formatted.

        Args:
            path: The path to validate

        Returns:
            bool: True if path is valid and accessible
        """
        pass

    # ==================== UI Configuration ====================

    def get_library_icon(self) -> str:
        """
        Get the Material Design Icon name for the library.

        Returns:
            str: MDI icon name (e.g., 'mdi-movie', 'mdi-television', 'mdi-gamepad-variant')
        """
        library_type = self.get_library_type().upper()
        default_icons = {
            "MOVIES": "mdi-movie",
            "SHOWS": "mdi-television",
            "GAMES": "mdi-gamepad-variant",
            "MUSIC": "mdi-music",
            "BOOKS": "mdi-book",
        }
        return default_icons.get(library_type, "mdi-folder")

    def get_item_icon(self) -> str:
        """
        Get the Material Design Icon name for individual items in this library.

        Returns:
            str: MDI icon name (e.g., 'mdi-movie', 'mdi-television', 'mdi-controller')
        """
        return self.get_library_icon()

    def get_play_button_icon(self) -> str:
        """
        Get the Material Design Icon name for the play/action button.

        Returns:
            str: MDI icon name (e.g., 'mdi-play', 'mdi-play-circle', 'mdi-book-open')
        """
        library_type = self.get_library_type().upper()
        default_icons = {
            "BOOKS": "mdi-book-open",
            "GAMES": "mdi-play",
            "MUSIC": "mdi-play",
            "MOVIES": "mdi-play",
            "SHOWS": "mdi-play",
        }
        return default_icons.get(library_type, "mdi-play")

    def get_play_button_label(self) -> str:
        """
        Get the translatable label key for the play/action button.

        Returns:
            str: Translation key (e.g., 'common.play', 'common.read', 'common.listen')
        """
        library_type = self.get_library_type().upper()
        default_labels = {
            "BOOKS": "common.read",
            "GAMES": "common.play",
            "MUSIC": "common.listen",
            "MOVIES": "common.play",
            "SHOWS": "common.play",
        }
        return default_labels.get(library_type, "common.play")

    # ==================== Library Initialization ====================

    async def initialize_library(self, path: str) -> bool:
        """
        Initialize/create a library at the given path.

        Args:
            path: The path where the library should be created

        Returns:
            bool: True if initialization succeeded
        """
        import os

        try:
            os.makedirs(path, exist_ok=True)
            logger.info("Initialized library at path=%s", path)
            return True
        except Exception:
            logger.error("Failed to initialize library at path=%s", path, exc_info=True)
            return False

    async def get_library_stats(self, path: str) -> dict[str, Any]:
        """
        Get statistics about the library (file count, size, etc.).

        Args:
            path: The library path

        Returns:
            dict: Statistics about the library
        """
        return {
            "path": path,
            "file_count": 0,
            "total_size": 0,
        }

    # ==================== Media Item Operations ====================

    async def scan_library(self, path: str) -> list[dict[str, Any]]:
        """
        Scan library path for media files and return discovered items.

        Args:
            path: The library path to scan

        Returns:
            list[dict]: List of discovered media files with metadata
        """
        return []

    async def match_media(self, file_info: dict[str, Any]) -> dict[str, Any] | None:
        """
        Match a media file to external metadata (TMDB, IGDB, etc.).

        Args:
            file_info: Information about the media file (path, name, etc.)

        Returns:
            dict | None: Matched media metadata or None if no match found
        """
        return None

    async def get_metadata_provider(self) -> str | None:
        """
        Get the preferred metadata provider for this media type.

        Returns:
            str | None: Provider name (e.g., 'tmdb', 'igdb', 'spotify') or None
        """
        return None

    async def format_file_path(
        self, media_info: dict[str, Any], library_path: str
    ) -> str:
        """
        Generate the proper file path/structure for media within library.

        Args:
            media_info: Media metadata (title, year, etc.)
            library_path: Base library path

        Returns:
            str: Formatted path for the media file
        """
        import os

        title = media_info.get("title", "Unknown")
        safe_title = "".join(c for c in title if c.isalnum() or c in (" ", "-", "_"))
        return os.path.join(library_path, safe_title)

    async def validate_media_file(self, file_path: str) -> bool:
        """
        Validate that a file is a valid media file for this library type.

        Args:
            file_path: Path to the file to validate

        Returns:
            bool: True if file is valid for this media type
        """
        import os

        return os.path.isfile(file_path)

    async def get_supported_extensions(self) -> list[str]:
        """
        Get list of supported file extensions for this media type.

        Returns:
            list[str]: List of supported extensions (e.g., ['.mkv', '.mp4'])
        """
        return []

    async def extract_metadata_from_filename(self, filename: str) -> dict[str, Any]:
        """
        Extract metadata from filename (year, quality, etc.).

        Args:
            filename: The filename to parse

        Returns:
            dict: Extracted metadata
        """
        return {}

    async def extract_release_metadata(self, release_title: str) -> dict[str, Any]:
        """
        Extract detailed metadata from a release title.

        Args:
            release_title: The full release title to parse

        Returns:
            dict: Extracted metadata (resolution, codec, source, languages, etc.)
        """
        return {}

    async def score_release(
        self, metadata: dict[str, Any], preferences: dict[str, Any] | None = None
    ) -> float:
        """
        Calculate a quality score for a release based on its metadata.

        Args:
            metadata: Release metadata extracted from extract_release_metadata()
            preferences: Optional user preferences for quality selection

        Returns:
            float: Quality score (0-100, higher is better)
        """
        return 50.0

    # Canonical codec aliases — release parsers extract "h265" from titles, while
    # supported_video_codecs from MediaCapabilities uses "hevc". Without this, an
    # x265 release scores as a codec mismatch for a client that supports HEVC.
    _CODEC_ALIASES: ClassVar[dict[str, str]] = {
        "h265": "hevc", "x265": "hevc", "hevc": "hevc",
        "h264": "h264", "x264": "h264", "avc": "h264",
        "av1": "av1", "vp9": "vp9", "vp8": "vp8",
        "mpeg4": "mpeg4", "xvid": "mpeg4", "divx": "mpeg4",
        "dd": "ac3", "ac3": "ac3", "dolby digital": "ac3",
        "ddp": "eac3", "eac3": "eac3", "e-ac3": "eac3", "dd+": "eac3",
        "dts-hd": "dts-hd", "dts": "dts", "dca": "dts",
        "truehd": "truehd", "tru-hd": "truehd",
        "atmos": "atmos", "aac": "aac", "mp3": "mp3", "opus": "opus",
        "flac": "flac", "vorbis": "vorbis", "pcm": "pcm",
    }

    @classmethod
    def _canon_codec(cls, name: str) -> str:
        """Normalize a codec string so aliases like h265/x265/hevc compare equal."""
        return cls._CODEC_ALIASES.get(name.lower().strip(), name.lower().strip())

    @staticmethod
    def score_release_age(metadata: dict[str, Any], preferences: dict[str, Any] | None = None) -> float:
        """Score based on release age (like Sonarr's age tiebreaker).

        Newer releases get a bonus, very old releases get a penalty.
        Also acts as a hard retention filter — releases older than max_retention_days
        are rejected (return large negative score).

        Returns a score adjustment (-20 to +10).
        """
        from datetime import datetime, timezone

        publish_date = metadata.get("publish_date")
        if not publish_date:
            return 0.0

        if isinstance(publish_date, str):
            try:
                publish_date = datetime.fromisoformat(publish_date.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                return 0.0

        now = datetime.now(timezone.utc)
        if publish_date.tzinfo is None:
            publish_date = publish_date.replace(tzinfo=timezone.utc)

        age_days = (now - publish_date).total_seconds() / 86400

        # Hard retention filter — reject releases older than max_retention_days
        max_retention = 0
        if preferences:
            max_retention = preferences.get("max_retention_days", 0)
        if max_retention > 0 and age_days > max_retention:
            return -1000.0  # Hard reject

        # Age scoring like Sonarr:
        # < 1 day: +10 (very fresh)
        # 1-7 days: +7
        # 7-30 days: +5
        # 30-180 days: +2
        # 180-365 days: 0
        # 1-2 years: -5
        # 2-4 years: -10
        # > 4 years: -15 (very old, likely DMCA'd)
        if age_days < 1:
            return 10.0
        elif age_days < 7:
            return 7.0
        elif age_days < 30:
            return 5.0
        elif age_days < 180:
            return 2.0
        elif age_days < 365:
            return 0.0
        elif age_days < 730:
            return -5.0
        elif age_days < 1460:
            return -10.0
        else:
            return -15.0

    def _finalize_release_score(
        self,
        score: float,
        metadata: dict[str, Any],
        preferences: dict[str, Any] | None,
        video_codec: str,
        audio_codecs: list[str],
    ) -> float:
        """Shared tail of ``score_release``: language, client codec-compat, age, clamp.

        This block was byte-identical between the movie and TV scorers (only the
        dimension weight tables that run before it genuinely differ). It lives
        here so the two can't silently diverge on language handling, the
        allowed-language hard-reject, retention filtering or the final clamp.
        """
        # Language scoring
        # user_languages: ordered list of ISO 639-1 codes (e.g. ['de', 'en'])
        # allowed_languages: list of ISO 639-1 codes permitted by the library admin
        user_languages: list[str] = (
            preferences.get("user_languages") or [] if preferences else []
        )
        # Backward compat: accept legacy single "user_language" key
        if not user_languages and preferences:
            legacy = preferences.get("user_language")
            if legacy:
                user_languages = [legacy]
        allowed_languages: list[str] = (
            preferences.get("allowed_languages", []) if preferences else []
        )
        release_languages: list[str] = metadata.get("languages", [])

        if release_languages:
            lang_match_bonus = (
                preferences.get("language_match_bonus", 10) if preferences else 10
            )
            matched_priority = False
            if user_languages:
                for priority, lang in enumerate(user_languages):
                    if lang in release_languages or "multi" in release_languages:
                        # Higher bonus for first preference, slightly less for later ones
                        bonus = max(1, lang_match_bonus - priority * 2)
                        score += bonus
                        matched_priority = True
                        break
            if (
                not matched_priority
                and allowed_languages
                and not any(lang in release_languages for lang in allowed_languages)
                and "multi" not in release_languages
            ):
                # Hard reject: release language not in allowed list
                return 0.0

        # Codec compatibility scoring
        # supported_video_codecs: list of video codecs the client can play natively
        # supported_audio_codecs: list of audio codecs the client can play natively
        # If the release uses a supported codec -> bonus; unsupported -> penalty
        if preferences:
            supported_video = {
                self._canon_codec(c) for c in preferences.get("supported_video_codecs", [])
            }
            supported_audio = {
                self._canon_codec(c) for c in preferences.get("supported_audio_codecs", [])
            }
            codec_match_bonus = preferences.get("codec_match_bonus", 0)
            codec_mismatch_penalty = preferences.get("codec_mismatch_penalty", 0)

            if supported_video and video_codec:
                if self._canon_codec(video_codec) in supported_video:
                    score += codec_match_bonus
                else:
                    score -= codec_mismatch_penalty

            if supported_audio and audio_codecs:
                release_audio_canon = {self._canon_codec(a) for a in audio_codecs}
                if release_audio_canon & supported_audio:
                    score += codec_match_bonus
                else:
                    score -= codec_mismatch_penalty

        # Release age scoring — prefer newer releases, penalize old ones
        age_score = self.score_release_age(metadata, preferences)
        if age_score <= -1000:
            return 0.0  # Hard retention reject
        score += age_score

        # Clamp to >= 0. No upper bound: sorting needs to distinguish releases
        # that would otherwise tie at 100 (e.g. language_match_bonus=50 plus a
        # strong 1080p h265 release pushes both above 100, hiding real differences).
        return max(0.0, score)

    async def handle_completed_download(
        self,
        *,
        download_context: dict[str, Any],
        files: list[Any],
        db: Any,
    ) -> dict[str, Any]:
        """Handle a completed download by importing files into the library.

        Args:
            download_context: Dict with keys:
                - download: The Download ORM object
                - media_item: The target MediaItem
                - release_metadata: dict from the release record (or {})
            files: List of Path objects pointing to downloaded video files
            db: The async SQLAlchemy session

        Returns:
            dict: Must contain at least ``{"success": True/False}``.
                On success, include ``files_imported`` (int).
                On failure, include ``error`` (str).
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement handle_completed_download"
        )

    async def probe_media_file(self, file_path: str) -> dict[str, Any]:
        """
        Probe a media file to extract technical metadata using ffprobe.

        Args:
            file_path: Path to the media file to probe

        Returns:
            dict: Structured probe data with keys:
                - format: ffprobe format metadata
                - video_streams: list of video stream dicts
                - audio_streams: list of audio stream dicts
                - subtitle_streams: list of subtitle stream dicts
        """
        logger.debug("Probing media file: %s", file_path)
        return {}

    def get_naming_schema(self) -> dict[str, Any]:
        """
        Get the naming schema for this library type.

        Returns:
            dict: Naming schema containing variables, defaults, and options.
        """
        return {
            "variables": [
                {
                    "name": "title",
                    "description": "Media title",
                    "example": "Example Title",
                },
                {"name": "year", "description": "Release year", "example": "2023"},
            ],
            "defaults": {"folder": "{title} ({year})", "file": "{title}"},
            "options": {"replace_illegal_characters": True, "colon_replacement": " -"},
        }

    def get_settings_schema(self) -> dict[str, Any]:
        """
        Get the settings schema for this library type.

        Returns:
            dict: Settings schema mapping field names to their definitions
        """
        return {
            "enable_library": {"default": True, "key": "enabled"},
            "library_path": {"default": "/library"},
        }

    def get_preview_data(self) -> dict[str, Any]:
        """
        Get sample media data for naming preview.

        Returns:
            dict: Sample media info dict for use with suggest_folder_name/suggest_file_name
        """
        return {"title": "Example Title", "year": 2023}

    async def suggest_folder_name(
        self,
        media_info: dict[str, Any],
        template: str | None = None,
        tmdb_id: int | None = None,
        imdb_id: str | None = None,
    ) -> str:
        """
        Generate a folder name using a template or default Trash Guide convention.

        Args:
            media_info: Media metadata (title, year, etc.)
            template: Optional template string (e.g., "{title} ({year})")
            tmdb_id: TMDb ID for the media
            imdb_id: IMDb ID for the media (alternative)

        Returns:
            str: Generated folder name
        """
        if template:
            result = await self._apply_template(
                template, media_info, tmdb_id=tmdb_id, imdb_id=imdb_id
            )
            logger.debug("suggest_folder_name: template=%r -> %r", template, result)
            return result

        title = media_info.get("title", "Unknown")
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

        logger.debug("suggest_folder_name: title=%r year=%s -> %r", title, year, folder)
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
        Suggest a file name following Trash Guide Plex/TMDb convention.

        Args:
            media_info: Media metadata (title, year, tmdb_id)
            release_metadata: Metadata extracted from release title
            probe_data: Technical metadata from probe_media_file()
            edition_tags: Edition information (e.g., "Director's Cut", "IMAX")
            custom_formats: List of custom format tags
            release_group: Release group name

        Returns:
            str: Suggested file name (without extension) following conventions
        """
        title = media_info.get("title", "Unknown")
        year = media_info.get("year", "")

        clean_title = self._clean_title(title)

        parts = [clean_title]

        if year:
            parts.append(f"({year})")

        result = " ".join(parts)
        logger.debug("suggest_file_name: title=%r year=%s -> %r", title, year, result)
        return result

    async def _apply_template(
        self,
        template: str,
        media_info: dict[str, Any],
        probe_data: dict[str, Any] | None = None,
        **extra_vars,
    ) -> str:
        """
        Apply a template string to generate a name.

        Args:
            template: Template string (e.g., "{title} ({year})")
            media_info: Media metadata dictionary
            probe_data: Optional probe data for quality/codec variables
            **extra_vars: Additional template variables

        Returns:
            str: Generated name with variables replaced
        """
        variables = {**media_info, **extra_vars}

        if probe_data:
            naming = extract_naming_metadata(probe_data) if "video_streams" in probe_data else probe_data
            variables.update(
                {
                    "resolution": naming.get("resolution", ""),
                    "video_codec": naming.get("video_codec", ""),
                    "audio_codec": naming.get("audio_codec", ""),
                    "audio_channels": naming.get("audio_channels", ""),
                    "hdr_format": naming.get("hdr_format", ""),
                }
            )

        # Single-pass substitution so that a value like ``title="Movie {year}"``
        # can't get its literal ``{year}`` re-expanded in a later iteration.
        def _fmt(value: Any) -> str:
            if isinstance(value, bool):
                return "yes" if value else "no"
            return str(value)

        def _lookup(match: re.Match) -> str:
            key = match.group(1)
            value = variables.get(key)
            if value is None:
                return ""
            return _fmt(value)

        result = re.sub(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", _lookup, template)
        return self._clean_title(result)

    def _clean_title(self, title: str) -> str:
        """
        Clean a title for use in file/folder names.

        Args:
            title: The title to clean

        Returns:
            str: Cleaned title safe for filesystem use
        """
        replacements = {
            ":": "",
            "/": "-",
            "\\": "-",
            "|": "-",
            "?": "",
            "*": "",
            '"': "'",
            "<": "",
            ">": "",
            "\n": " ",
            "\r": " ",
        }

        cleaned = title
        for old, new in replacements.items():
            cleaned = cleaned.replace(old, new)

        cleaned = " ".join(cleaned.split())

        return cleaned.strip()

    def get_config_schema(self) -> dict[str, Any]:
        """
        Get the configuration schema for this library.

        Returns:
            dict: Configuration schema with field definitions
        """
        return {}

    async def validate_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """
        Validate library configuration.

        Args:
            config: Configuration dictionary to validate

        Returns:
            dict: Validation result with 'valid' (bool), 'errors' (list of str)
        """
        return {"valid": True, "errors": []}

    # ==================== Video Library Utilities ====================
    # Shared methods for video-based libraries (movies, shows).
    # Naming/formatting follows Trash Guide conventions.
    # Note: _clean_title above (dict-based replacements) is the canonical
    # implementation; an earlier copy in this section silently shadowed
    # it with a weaker regex that lost colon/slash/newline handling.

    def _format_quality_tag(self, source: str | None = None, resolution: str | None = None) -> str:
        if source and resolution:
            return f"[{source} {resolution}]"
        elif resolution:
            return f"[{resolution}]"
        elif source:
            return f"[{source}]"
        return ""

    def _format_audio_tag(self, audio_codec: str | None = None, audio_channels: str | None = None) -> str:
        if audio_codec:
            s = audio_codec
            if audio_channels:
                s += f" {audio_channels}"
            return f"[{s}]"
        return ""

    def _format_hdr_tag(self, hdr_format: str | None = None) -> str:
        return f"[{hdr_format}]" if hdr_format else ""

    def _format_video_codec_tag(self, video_codec: str | None = None) -> str:
        if video_codec:
            display = {"h264": "x264", "h265": "x265", "hevc": "x265", "av1": "AV1"}.get(
                video_codec.lower(), video_codec.upper()
            )
            return f"[{display}]"
        return ""

    def _format_release_group_tag(self, release_group: str | None = None) -> str:
        return f"-{release_group}" if release_group else ""

    def _format_edition_tag(self, edition_tags: str | None = None) -> str:
        return edition_tags if edition_tags else ""

    def _format_custom_formats_tag(self, custom_formats: list[str] | None = None) -> str:
        return f"[{' '.join(custom_formats)}]" if custom_formats else ""
