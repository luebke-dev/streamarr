"""
Release parsing utilities for extracting metadata from release titles.

This module provides regex patterns and helper functions for parsing
release names across different media types (movies, TV shows, music, games).
"""

import logging
import re
import unicodedata
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ParsedMovieRelease:
    """Parsed movie release information."""

    title: str
    year: int | None
    original_title: str


@dataclass
class ParsedShowRelease:
    """Parsed TV show release information."""

    title: str
    season: int | None
    episode: int | None
    episode_end: int | None  # For multi-episode releases (e.g., S01E01-E03)
    year: int | None
    original_title: str
    is_season_pack: bool = False
    is_complete_series: bool = False


@dataclass
class ParsedMusicRelease:
    """Parsed music release information."""

    artist: str
    title: str  # Album or song title
    year: int | None
    audio_format: str | None  # FLAC, MP3, AAC, etc.
    bitrate: str | None  # 320, V0, Lossless, etc.
    original_title: str


class ReleaseParser:
    """Utility class for parsing release names and extracting metadata."""

    # Video quality patterns
    RESOLUTION_PATTERN = re.compile(r"\b(\d{3,4}p|2160p|4320p)\b", re.IGNORECASE)
    QUALITY_PATTERN = re.compile(r"\b(480p|720p|1080p|2160p|4320p)\b", re.IGNORECASE)

    # Synonyms for resolutions when no explicit tag is present
    # Only unambiguous synonyms — 4K/UHD clearly mean 2160p, 8K means 4320p
    RESOLUTION_SYNONYMS = [
        (re.compile(r"\b(4K|UHD)\b", re.IGNORECASE), "2160p"),
        (re.compile(r"\b(8K)\b", re.IGNORECASE), "4320p"),
    ]

    # Source patterns
    SOURCE_PATTERN = re.compile(
        r"\b(BluRay|BD|BDRip|BRRip|WEB-?DL|WEB-?HD|WEB-?SCREENER|WEBRip|WEB|HDTV|DVDRip|DVD|HDCAM|HDTS|CAM|TS|TC|TELESYNC|TELECINE|REMUX)\b",
        re.IGNORECASE,
    )
    # Streaming service tags that imply WEB-DL source
    STREAMING_SERVICE_PATTERN = re.compile(
        r"\b(AMZN|ATVP|DSNP|NF|HMAX|HULU|PMTP|PCOK|iT|STAN|RED|CRAV|MA|SHO|STRP|VL)\b",
    )

    # Codec patterns
    VIDEO_CODEC_PATTERN = re.compile(
        r"\b(x264|x265|h\.?264|h\.?265|HEVC|AVC|XviD|DivX|VP9|AV1|MPEG-?2)\b",
        re.IGNORECASE,
    )
    AUDIO_CODEC_PATTERN = re.compile(
        r"\b(AAC|AC-?3|E-?AC-?3|EAC3|DTS|DTS-?HD|DTS-?MA|TrueHD|FLAC|Opus|MP3|Vorbis|ATMOS|DD\+?)\b",
        re.IGNORECASE,
    )

    # Language patterns — full names, ISO-style abbreviations, and special tags
    LANGUAGE_PATTERN = re.compile(
        r"\b("
        # Full names
        r"GERMAN|ENGLISH|FRENCH|SPANISH|ITALIAN|JAPANESE|CHINESE|KOREAN|"
        r"DUTCH|PORTUGUESE|RUSSIAN|POLISH|CZECH|HUNGARIAN|SWEDISH|NORWEGIAN|"
        r"DANISH|FINNISH|TURKISH|ARABIC|HEBREW|HINDI|THAI|"
        # Common abbreviations (Sonarr-style)
        r"GER|ENG|FRE|SPA|ITA|JPN|KOR|NLD|POR|RUS|POL|CZE|HUN|SWE|NOR|DAN|FIN|TUR|ARA|"
        # Special tags
        r"MULTI|DL|DUBBED|SUBBED|TRUEFRENCH|VOSTFR|"
        # Asian language tags
        r"CHS|CHT"
        r")\b",
        re.IGNORECASE,
    )
    # German dub pattern (separate for "GER.DUB", "GER.DUBBED")
    LANGUAGE_DUB_PATTERN = re.compile(
        r"\b(GER|ENG|FRE|SPA|ITA)[\.\s_-]?(DUB|DUBBED)\b", re.IGNORECASE
    )

    # Music-specific patterns
    AUDIO_FORMAT_PATTERN_MUSIC = re.compile(
        r"\b(FLAC|MP3|AAC|M4A|OGG|WMA|WAV|Opus|ALAC|APE)\b", re.IGNORECASE
    )
    BITRATE_PATTERN = re.compile(
        r"\b(320|256|192|128|96|64)\s*k(?:bps?)?\b|\b(V0|V2|CBR|VBR|Lossless|24bit|16bit)\b",
        re.IGNORECASE,
    )
    # Artist - Title separator pattern
    MUSIC_SEPARATOR_RE = re.compile(r"\s+[-–—]\s+")

    # Special markers
    HDR_PATTERN = re.compile(
        r"\b(HDR10\+|HDR10|HDR|Dolby[ -]?Vision|DV|HLG)\b", re.IGNORECASE
    )
    REMUX_PATTERN = re.compile(r"\bREMUX\b", re.IGNORECASE)
    PROPER_REPACK_PATTERN = re.compile(
        r"\b(PROPER|REPACK|REAL|REAL\.PROPER)\b", re.IGNORECASE
    )
    RELEASE_GROUP_PATTERN = re.compile(r"-([A-Z0-9]+)(?:\[.*\])?$", re.IGNORECASE)

    # Container formats
    CONTAINER_PATTERN = re.compile(
        r"\.(mkv|mp4|avi|mov|m4v|wmv|flv|webm|mpg|mpeg|ts)$", re.IGNORECASE
    )

    # Audio channels
    AUDIO_CHANNELS_PATTERN = re.compile(r"\b([257])\.([01])\b")

    # ==================== Title Extraction Patterns ====================

    # TV Show episode patterns (various formats)
    # S01E01, S01E01E02, S01E01-E03, S1E1, 1x01, etc.
    TV_EPISODE_PATTERN = re.compile(
        r"[\.\s_-]S(\d{1,2})[\.\s_-]?E(\d{1,3})(?:[\.\s_-]?E(\d{1,3})|[\.\s_-]?-[\.\s_-]?E?(\d{1,3}))?[\.\s_-]",
        re.IGNORECASE,
    )
    # Alternative format: 1x01
    TV_EPISODE_ALT_PATTERN = re.compile(
        r"[\.\s_-](\d{1,2})x(\d{1,3})[\.\s_-]",
        re.IGNORECASE,
    )
    # Season pack: S01, Season 1, Season.1
    TV_SEASON_PACK_PATTERN = re.compile(
        r"[\.\s_-](?:S(\d{1,2})|Season[\.\s_-]?(\d{1,2}))[\.\s_-](?!E\d)",
        re.IGNORECASE,
    )
    # Complete series markers
    TV_COMPLETE_PATTERN = re.compile(
        r"\b(Complete|COMPLETE\.Series|Complete\.Series|Staffel\.1-\d+)\b",
        re.IGNORECASE,
    )

    # Year pattern (1900-2099) — must be preceded by a separator, followed by separator or end-of-string
    YEAR_PATTERN = re.compile(r"[\.\s_\(\[-]((?:19|20)\d{2})(?:[\.\s_\)\]-]|$)")

    # Noise words to remove from titles
    NOISE_WORDS = re.compile(
        r"\b(UNCUT|UNRATED|EXTENDED|DIRECTORS\.?CUT|THEATRICAL|IMAX|REMASTERED|"
        r"ANNIVERSARY|EDITION|DC|SE|CE|LIMITED|SPECIAL|CRITERION)\b",
        re.IGNORECASE,
    )

    # Pattern to find where quality/technical info starts
    # This helps us identify where the title ends
    TECHNICAL_START_PATTERN = re.compile(
        r"[\.\s_-](480p|720p|1080p|2160p|4320p|BluRay|BD|BDRip|BRRip|WEB-?DL|WEB-?HD|WEB-?SCREENER|WEBRip|"
        r"HDTV|DVDRip|DVD|HDCAM|HDTS|CAM|TS|TC|REMUX|x264|x265|h\.?264|h\.?265|HEVC|AVC|"
        r"AAC|AC3|DTS|FLAC|GERMAN|ENGLISH|FRENCH|MULTI|DL|HDR|Atmos)[\.\s_-]",
        re.IGNORECASE,
    )

    @classmethod
    def normalize_title(cls, title: str) -> str:
        """
        Normalize a title for comparison.

        - Converts to lowercase
        - Removes accents/diacritics
        - Removes special characters
        - Normalizes whitespace
        - Removes common noise words
        """
        if not title:
            return ""

        # Convert to lowercase
        normalized = title.lower()

        # Remove accents/diacritics (e.g., é -> e, ü -> u)
        normalized = unicodedata.normalize("NFKD", normalized)
        normalized = "".join(c for c in normalized if not unicodedata.combining(c))

        # Replace common separators with spaces
        normalized = re.sub(r"[._-]+", " ", normalized)

        # Remove special characters except alphanumeric and spaces
        normalized = re.sub(r"[^a-z0-9\s]", "", normalized)

        # Remove noise words
        normalized = cls.NOISE_WORDS.sub("", normalized)

        # Normalize whitespace
        normalized = " ".join(normalized.split())

        return normalized.strip()

    @classmethod
    def parse_movie_release(cls, release_title: str) -> ParsedMovieRelease:
        """
        Parse a movie release title to extract the movie title and year.

        Examples:
            "Movie.Title.2023.1080p.BluRay.x264-GROUP" -> ("Movie Title", 2023)
            "The.Movie.2020.GERMAN.DL.1080p.WEB.x264-GROUP" -> ("The Movie", 2020)
        """
        original = release_title
        title = release_title

        # Remove file extension if present
        title = cls.CONTAINER_PATTERN.sub("", title)

        # Remove release group at end
        title = cls.RELEASE_GROUP_PATTERN.sub("", title)

        # Try to find year first
        year = None
        year_match = cls.YEAR_PATTERN.search(title)
        if year_match:
            year = int(year_match.group(1))

        # Find where technical info starts
        tech_match = cls.TECHNICAL_START_PATTERN.search(title)
        if tech_match:
            title = title[: tech_match.start()]
        elif year_match:
            # If no technical match, cut at year
            title = title[: year_match.start()]

        # Clean up the title
        title = re.sub(r"[._-]+", " ", title)
        title = title.strip()

        # Remove trailing year if it's part of the title
        title = re.sub(r"\s*\(\d{4}\)\s*$", "", title)
        title = re.sub(r"\s*\d{4}\s*$", "", title)

        result = ParsedMovieRelease(
            title=title.strip(),
            year=year,
            original_title=original,
        )
        logger.debug("parse_movie_release: %r -> title=%r year=%s", original, result.title, result.year)
        return result

    @classmethod
    def parse_show_release(cls, release_title: str) -> ParsedShowRelease:
        """
        Parse a TV show release title to extract show title, season, and episode.

        Examples:
            "Show.Name.S01E05.1080p.WEB.x264" -> ("Show Name", 1, 5)
            "Show.Name.2019.S02E10.720p.HDTV" -> ("Show Name", 2, 10, year=2019)
            "Show.Name.S01.COMPLETE.1080p" -> ("Show Name", 1, None, is_season_pack=True)
        """
        original = release_title
        title = release_title

        # Remove file extension if present
        title = cls.CONTAINER_PATTERN.sub("", title)

        # Remove release group at end
        title = cls.RELEASE_GROUP_PATTERN.sub("", title)

        season = None
        episode = None
        episode_end = None
        is_season_pack = False
        is_complete = False

        # Check for complete series
        if cls.TV_COMPLETE_PATTERN.search(title):
            is_complete = True

        # Try standard S01E01 format
        ep_match = cls.TV_EPISODE_PATTERN.search(title)
        if ep_match:
            season = int(ep_match.group(1))
            episode = int(ep_match.group(2))
            # Check for multi-episode (E01E02 or E01-E03)
            if ep_match.group(3):
                episode_end = int(ep_match.group(3))
            elif ep_match.group(4):
                episode_end = int(ep_match.group(4))
            # Title is everything before the episode marker
            title = title[: ep_match.start()]
        else:
            # Try alternative 1x01 format
            ep_alt_match = cls.TV_EPISODE_ALT_PATTERN.search(title)
            if ep_alt_match:
                season = int(ep_alt_match.group(1))
                episode = int(ep_alt_match.group(2))
                title = title[: ep_alt_match.start()]
            else:
                # Check for season pack
                season_match = cls.TV_SEASON_PACK_PATTERN.search(title)
                if season_match:
                    season = int(season_match.group(1) or season_match.group(2))
                    is_season_pack = True
                    title = title[: season_match.start()]

        # Extract year (often appears before season info)
        year = None
        year_match = cls.YEAR_PATTERN.search(title)
        if year_match:
            year = int(year_match.group(1))
            # Don't remove year from title as it might be part of the show name
            # (e.g., "Doctor Who 2005")

        # Find where technical info starts and cut there
        tech_match = cls.TECHNICAL_START_PATTERN.search(title)
        if tech_match:
            title = title[: tech_match.start()]

        # Clean up the title
        title = re.sub(r"[._-]+", " ", title)
        title = title.strip()

        # Remove trailing year if not part of show name
        # Keep year if it looks like "Show Name 2019" pattern
        title_with_year = title
        title = re.sub(r"\s*\(\d{4}\)\s*$", "", title)

        result = ParsedShowRelease(
            title=title.strip() or title_with_year.strip(),
            season=season,
            episode=episode,
            episode_end=episode_end,
            year=year,
            original_title=original,
            is_season_pack=is_season_pack,
            is_complete_series=is_complete,
        )
        logger.debug(
            "parse_show_release: %r -> title=%r S%sE%s year=%s",
            original, result.title, season, episode, year,
        )
        return result

    @classmethod
    def extract_resolution(cls, title: str) -> str | None:
        """
        Extract resolution from release title.

        First checks for an explicit resolution tag (e.g., "1080p", "720p").
        If none is found, infers resolution from the source type:
        - DVD/DVDRip → 480p (SD)
        - CAM/TS/TC/Telesync/Telecine → 480p (SD)
        - HDTV without explicit resolution → 720p (common default)

        Returns:
            Resolution string (e.g., "1080p", "2160p", "480p") or None
        """
        match = cls.RESOLUTION_PATTERN.search(title)
        if match:
            return match.group(1).lower()

        # Check synonyms (4K → 2160p, UHD → 2160p, FHD → 1080p, etc.)
        # Use word-boundary patterns to avoid false positives
        for pattern, resolution in cls.RESOLUTION_SYNONYMS:
            # Skip the explicit resolution patterns already checked above
            if pattern.search(title):
                return resolution

        # Infer resolution from source type when no explicit resolution is present
        source = cls.extract_source(title)
        if source:
            # SD sources
            if source in ("dvd", "telesync", "telecine", "cam"):
                return "480p"
            # HDTV without explicit resolution is typically 720p
            if source == "hdtv":
                return "720p"

        return None

    @classmethod
    def extract_source(cls, title: str) -> str | None:
        """
        Extract source from release title.

        Returns:
            Normalized source string or None
        """
        match = cls.SOURCE_PATTERN.search(title)
        if match:
            source = match.group(1).lower().replace("-", "").replace(".", "")
            # Normalize variations
            if source in ["bd", "bdrip", "brrip", "bluray"]:
                return "bluray"
            if source in ["webdl", "webhd", "web"]:
                return "web-dl"
            if source in ["webrip"]:
                return "webrip"
            if source == "remux":
                return "remux"
            if source in ["ts", "telesync", "hdts"]:
                return "telesync"
            if source in ["tc", "telecine"]:
                return "telecine"
            if source in ["cam", "hdcam"]:
                return "cam"
            if source in ["webscreener", "screener", "scr"]:
                return "screener"
            if source in ["dvd", "dvdrip"]:
                return "dvd"
            return source

        # Fallback: streaming service tag implies WEB-DL
        if cls.STREAMING_SERVICE_PATTERN.search(title):
            return "web-dl"

        return None

    @classmethod
    def extract_video_codec(cls, title: str) -> str | None:
        """
        Extract video codec from release title.

        Returns:
            Normalized codec string or None
        """
        match = cls.VIDEO_CODEC_PATTERN.search(title)
        if match:
            codec = match.group(1).lower().replace(".", "")
            # Normalize variations
            if codec in ["x264", "avc", "h264"]:
                return "h264"
            if codec in ["x265", "hevc", "h265"]:
                return "h265"
            if codec in ["mpeg2", "mpeg-2"]:
                return "mpeg2"
            return codec
        return None

    @classmethod
    def extract_audio_codec(cls, title: str) -> list[str]:
        """
        Extract audio codecs from release title.

        Returns:
            List of normalized codec strings
        """
        codecs = []
        for match in cls.AUDIO_CODEC_PATTERN.finditer(title):
            codec = match.group(1).lower().replace("-", "").replace(".", "")
            # Normalize variations
            if codec in ["eac3", "eac3", "ddp", "dd+"]:
                codec = "eac3"
            elif codec in ["ac3", "dd"]:
                codec = "ac3"
            elif codec in ["dtshd", "dtsma", "dts-hd", "dts-ma"]:
                codec = "dts-hd"
            elif codec == "truehd":
                codec = "truehd"

            if codec not in codecs:
                codecs.append(codec)

        return codecs

    @classmethod
    def extract_languages(cls, title: str) -> list[str]:
        """
        Extract languages from release title.

        Returns:
            List of ISO 639-1 language codes
        """
        languages = []
        title_upper = title.upper()

        # Check for DL (Dual Language - typically German + English)
        # Must be standalone word, not part of "WEB-DL" or "DOWNLOAD"
        if re.search(r"(?<![A-Z-])DL(?![A-Z])", title_upper) or "DUAL" in title_upper:
            return ["de", "en"]

        # Check for MULTI
        if "MULTI" in title_upper:
            return ["multi"]

        # Check for TRUEFRENCH / VOSTFR (French-specific)
        if "TRUEFRENCH" in title_upper:
            return ["fr"]
        if "VOSTFR" in title_upper:
            languages.append("fr")

        # Check for specific languages (full names + abbreviations)
        lang_map = {
            # Full names
            "GERMAN": "de", "ENGLISH": "en", "FRENCH": "fr",
            "SPANISH": "es", "ITALIAN": "it", "JAPANESE": "ja",
            "CHINESE": "zh", "KOREAN": "ko", "DUTCH": "nl",
            "PORTUGUESE": "pt", "RUSSIAN": "ru", "POLISH": "pl",
            "CZECH": "cs", "HUNGARIAN": "hu", "SWEDISH": "sv",
            "NORWEGIAN": "no", "DANISH": "da", "FINNISH": "fi",
            "TURKISH": "tr", "ARABIC": "ar", "HEBREW": "he",
            "HINDI": "hi", "THAI": "th",
            # Abbreviations (Sonarr-style)
            "GER": "de", "ENG": "en", "FRE": "fr",
            "SPA": "es", "ITA": "it", "JPN": "ja",
            "KOR": "ko", "NLD": "nl", "POR": "pt",
            "RUS": "ru", "POL": "pl", "CZE": "cs",
            "HUN": "hu", "SWE": "sv", "NOR": "no",
            "DAN": "da", "FIN": "fi", "TUR": "tr",
            "ARA": "ar",
            # Asian tags
            "CHS": "zh", "CHT": "zh",
        }

        # Use regex to match whole words only (avoids false positives)
        for lang_name, lang_code in lang_map.items():
            if re.search(rf"\b{lang_name}\b", title_upper):
                if lang_code not in languages:
                    languages.append(lang_code)

        # Check for dub patterns (e.g., "GER.DUB", "ENG.DUBBED")
        dub_match = cls.LANGUAGE_DUB_PATTERN.search(title)
        if dub_match:
            dub_lang = dub_match.group(1).upper()
            dub_code = lang_map.get(dub_lang)
            if dub_code and dub_code not in languages:
                languages.append(dub_code)

        # Default to English if no language specified
        if not languages:
            languages.append("en")

        return languages

    @classmethod
    def extract_audio_channels(cls, title: str) -> str | None:
        """
        Extract audio channel configuration.

        Returns:
            Channel string (e.g., "5.1", "7.1", "2.0") or None
        """
        match = cls.AUDIO_CHANNELS_PATTERN.search(title)
        if match:
            return f"{match.group(1)}.{match.group(2)}"

        # Check for common variations
        if "7.1" in title or "71" in title:
            return "7.1"
        if "5.1" in title or "51" in title:
            return "5.1"
        if "2.0" in title or "STEREO" in title.upper():
            return "2.0"

        return None

    @classmethod
    def extract_release_group(cls, title: str) -> str | None:
        """
        Extract release group from release title.

        Returns:
            Release group name or None
        """
        match = cls.RELEASE_GROUP_PATTERN.search(title)
        return match.group(1).upper() if match else None

    @classmethod
    def has_hdr(cls, title: str) -> bool:
        """Check if release has HDR."""
        return bool(cls.HDR_PATTERN.search(title))

    @classmethod
    def has_dolby_vision(cls, title: str) -> bool:
        """Check if release has Dolby Vision."""
        return bool(re.search(r"\b(Dolby[ -]?Vision|DV)\b", title, re.IGNORECASE))

    @classmethod
    def is_remux(cls, title: str) -> bool:
        """Check if release is a remux."""
        return bool(cls.REMUX_PATTERN.search(title))

    @classmethod
    def is_3d(cls, title: str) -> bool:
        """Check if release is 3D."""
        return bool(re.search(r"\b3D\b", title, re.IGNORECASE))

    @classmethod
    def has_proper_or_repack(cls, title: str) -> tuple[bool, bool]:
        """
        Check if release is marked as PROPER or REPACK.

        Returns:
            Tuple of (is_proper, is_repack)
        """
        text = title.upper()
        is_proper = "PROPER" in text or "REAL.PROPER" in text
        is_repack = "REPACK" in text
        return is_proper, is_repack

    @classmethod
    def extract_container(cls, title: str) -> str | None:
        """
        Extract container format from filename.

        Returns:
            Container format (e.g., "mkv", "mp4") or None
        """
        match = cls.CONTAINER_PATTERN.search(title)
        return match.group(1).lower() if match else None

    # ==================== Music Release Parsing ====================

    @classmethod
    def parse_music_release(cls, release_title: str) -> ParsedMusicRelease:
        """
        Parse a music release title to extract artist, title, year, format, and bitrate.

        Common formats:
            "Artist - Album (2024) [FLAC]"
            "Artist - Album (2024) [MP3 320]"
            "Artist_-_Album-2024-FLAC-GROUP"
            "Artist - Album - 2024 - FLAC - GROUP"
        """
        original = release_title
        title = release_title

        # Remove file extension
        title = cls.CONTAINER_PATTERN.sub("", title)

        # Remove release group at end
        title = cls.RELEASE_GROUP_PATTERN.sub("", title)

        # Extract audio format
        audio_format = None
        fmt_match = cls.AUDIO_FORMAT_PATTERN_MUSIC.search(title)
        if fmt_match:
            audio_format = fmt_match.group(1).upper()

        # Extract bitrate
        bitrate = None
        br_match = cls.BITRATE_PATTERN.search(title)
        if br_match:
            bitrate = br_match.group(1) or br_match.group(2)
            if bitrate and bitrate.isdigit():
                bitrate = f"{bitrate}kbps"

        # Extract year
        year = None
        year_match = cls.YEAR_PATTERN.search(title)
        if year_match:
            year = int(year_match.group(1))

        # Remove technical tokens (format, bitrate, year, brackets)
        cleaned = re.sub(
            r"\[.*?\]|\((?:\d{4}|FLAC|MP3|AAC|WEB|CD|Vinyl|Lossless|320kbps?|256kbps?|V0|VBR|CBR)\)",
            "",
            title,
            flags=re.IGNORECASE,
        )
        # Remove format/bitrate/year tokens from the remaining string
        cleaned = cls.AUDIO_FORMAT_PATTERN_MUSIC.sub("", cleaned)
        cleaned = cls.BITRATE_PATTERN.sub("", cleaned)
        cleaned = re.sub(r"\b(WEB|CD|Vinyl|Retail|SCENE)\b", "", cleaned, flags=re.IGNORECASE)

        # Try to split on "Artist - Title" separator
        parts = cls.MUSIC_SEPARATOR_RE.split(cleaned, maxsplit=1)
        if len(parts) >= 2:
            artist = parts[0].strip()
            album_title = parts[1].strip()
        else:
            # No separator — try dot/underscore separator
            cleaned_dots = re.sub(r"[._]+", " ", cleaned)
            parts = cls.MUSIC_SEPARATOR_RE.split(cleaned_dots, maxsplit=1)
            if len(parts) >= 2:
                artist = parts[0].strip()
                album_title = parts[1].strip()
            else:
                # Can't split — use whole string as title, empty artist
                artist = ""
                album_title = cleaned_dots.strip()

        # Clean up whitespace
        artist = re.sub(r"\s+", " ", artist).strip()
        album_title = re.sub(r"\s+", " ", album_title).strip()

        # Remove trailing year/noise from album title
        album_title = re.sub(r"\s*\(?\d{4}\)?\s*$", "", album_title).strip()
        album_title = re.sub(r"\s*[-–]\s*$", "", album_title).strip()

        result = ParsedMusicRelease(
            artist=artist,
            title=album_title,
            year=year,
            audio_format=audio_format,
            bitrate=bitrate,
            original_title=original,
        )
        logger.debug(
            "parse_music_release: %r -> artist=%r title=%r year=%s fmt=%s",
            original, result.artist, result.title, year, audio_format,
        )
        return result

    @classmethod
    def extract_audio_format(cls, title: str) -> str | None:
        """Extract audio format (FLAC, MP3, AAC, etc.) from a release title."""
        match = cls.AUDIO_FORMAT_PATTERN_MUSIC.search(title)
        return match.group(1).upper() if match else None

    @classmethod
    def extract_bitrate(cls, title: str) -> str | None:
        """Extract bitrate info from a release title."""
        match = cls.BITRATE_PATTERN.search(title)
        if match:
            val = match.group(1) or match.group(2)
            if val and val.isdigit():
                return f"{val}kbps"
            return val
        return None

    # Pattern for low quality sources — must match as whole words to avoid
    # false positives (e.g. "TS" in group name "TSCC")
    _LOW_QUALITY_RE = re.compile(
        r"(?:^|[\.\s_\-\[])("
        r"CAM|TELESYNC|TELECINE|TS|TC|WORKPRINT|R5|SCREENER|SCR|HDCAM|HQCAM|HDTS|WEB-?SCREENER"
        r")(?=$|[\.\s_\-\]])",
        re.IGNORECASE,
    )

    @classmethod
    def is_low_quality(cls, title: str) -> bool:
        """
        Check if release is low quality (CAM, TELESYNC, etc.).

        Uses word-boundary matching to avoid false positives
        (e.g. "TS" must not match in group names like "TSCC").
        """
        return bool(cls._LOW_QUALITY_RE.search(title))
