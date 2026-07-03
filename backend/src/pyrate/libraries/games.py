"""Game library plugin."""

import logging
import os
import re
from pathlib import Path
from typing import Any

from pyrate.libraries.base import LibraryBase

logger = logging.getLogger(__name__)

# Common PC game release groups
TRUSTED_GAME_GROUPS = [
    "CODEX", "PLAZA", "SKIDROW", "GOG", "RELOADED", "HOODLUM",
    "DODI", "FITGIRL", "KAOS", "RUNE", "TENOKE", "RAZOR1911",
    "PROPHET", "CPY", "EMPRESS", "GOLDBERG", "TiNYiSO",
]

# Platform patterns
_PLATFORM_RE = re.compile(
    r"\b(PC|Windows|Linux|Mac(?:OS)?|PS[2-5]|PS4|PS3|Xbox|XB1|XSX|Switch|NSW|3DS|NDS|GBA|Wii|WiiU|N64|SNES|Genesis|Dreamcast)\b",
    re.IGNORECASE,
)

# Game format patterns
_FORMAT_RE = re.compile(
    r"\b(ISO|GOG|Steam|NSP|XCI|CIA|PKG|XBLA|ROM|Repack|Portable)\b",
    re.IGNORECASE,
)


class GameLibraryPlugin(LibraryBase):
    """Plugin for managing game libraries."""

    def get_name(self) -> str:
        return "Game Library"

    def get_library_type(self) -> str:
        return "GAMES"

    async def get_default_path(self) -> str:
        return "/library/games"

    async def validate_path(self, path: str) -> bool:
        """Validate game library path."""
        try:
            path_obj = Path(path)
            if path_obj.exists():
                return path_obj.is_dir()
            return path_obj.parent.exists() and os.access(path_obj.parent, os.W_OK)
        except Exception as e:
            logger.error("Error validating game library path %s: %s", path, e)
            return False

    async def extract_release_metadata(self, release_title: str) -> dict[str, Any]:
        """Extract game-specific metadata from a release title."""
        metadata: dict[str, Any] = {
            "original_title": release_title,
            "platform": "PC",
            "game_format": None,
            "release_group": None,
            "is_repack": False,
            "is_update": False,
            "is_dlc": False,
        }

        title_upper = release_title.upper()

        # Platform
        platform_match = _PLATFORM_RE.search(release_title)
        if platform_match:
            plat = platform_match.group(1).upper()
            # Normalize
            if plat in ("NSW", "SWITCH"):
                metadata["platform"] = "Switch"
            elif plat in ("XB1", "XSX", "XBOX"):
                metadata["platform"] = "Xbox"
            elif plat in ("MACOS", "MAC"):
                metadata["platform"] = "Mac"
            else:
                metadata["platform"] = plat

        # Format
        fmt_match = _FORMAT_RE.search(release_title)
        if fmt_match:
            metadata["game_format"] = fmt_match.group(1).upper()

        # Release group (last hyphenated word)
        group_match = re.search(r"-(\w+)$", release_title.rstrip())
        if group_match:
            metadata["release_group"] = group_match.group(1)

        # Flags
        metadata["is_repack"] = bool(re.search(r"\bREPACK\b", title_upper))
        metadata["is_update"] = bool(re.search(r"\bUPDATE\b", title_upper))
        metadata["is_dlc"] = bool(re.search(r"\bDLC\b", title_upper))

        return metadata

    async def score_release(
        self, metadata: dict[str, Any], preferences: dict[str, Any] | None = None
    ) -> float:
        """Score a game release. PC preferred for Lightrays streaming."""
        score = 0.0

        # Platform scoring (0-30) — PC is best for Lightrays
        platform = metadata.get("platform", "").upper()
        if platform == "PC":
            score += 30
        elif platform in ("WINDOWS", "LINUX"):
            score += 28
        elif platform == "MAC":
            score += 15
        elif platform == "SWITCH":
            score += 10
        elif platform.startswith("PS"):
            score += 8
        elif platform.startswith("XBOX"):
            score += 8
        else:
            score += 5

        # Format scoring (0-15)
        fmt = (metadata.get("game_format") or "").upper()
        if fmt == "GOG":
            score += 15  # DRM-free, best
        elif fmt == "ISO":
            score += 12
        elif fmt == "STEAM":
            score += 10
        elif fmt in ("NSP", "XCI", "CIA", "PKG"):
            score += 8  # Console formats
        elif fmt == "REPACK":
            score += 13  # Usually well-tested
        else:
            score += 10  # Unknown format, assume OK

        # Release group trust (0-10)
        group = (metadata.get("release_group") or "").upper()
        if group in TRUSTED_GAME_GROUPS:
            score += 10
        elif group:
            score += 5

        # Penalties
        if metadata.get("is_update"):
            score -= 15  # Updates alone aren't useful
        if metadata.get("is_dlc"):
            score -= 10  # DLC alone not useful

        # Repack bonus (smaller download)
        if metadata.get("is_repack"):
            score += 5

        # Release age scoring
        age_score = self.score_release_age(metadata, preferences)
        if age_score <= -1000:
            return 0.0
        score += age_score

        return min(100.0, max(0.0, score))

    async def get_library_stats(self, path: str) -> dict[str, Any]:
        """Get statistics about the game library."""
        stats = {
            "path": path,
            "file_count": 0,
            "total_size": 0,
            "file_types": {},
        }

        try:
            path_obj = Path(path)
            if not path_obj.exists():
                return stats

            game_extensions = {
                ".iso", ".bin", ".cue", ".nsp", ".xci", ".cia",
                ".3ds", ".nds", ".gba", ".gb", ".gbc",
                ".z64", ".n64", ".v64", ".sfc", ".smc",
                ".zip", ".7z", ".exe", ".msi",
            }

            for file_path in path_obj.rglob("*"):
                if file_path.is_file():
                    ext = file_path.suffix.lower()
                    if ext in game_extensions:
                        stats["file_count"] += 1
                        stats["total_size"] += file_path.stat().st_size
                        stats["file_types"][ext] = stats["file_types"].get(ext, 0) + 1

        except Exception as e:
            logger.error("Error getting game library stats for %s: %s", path, e)

        return stats

    def get_settings_schema(self) -> dict[str, Any]:
        return {
            "enable_library": {"default": True, "key": "enabled"},
            "library_path": {"default": "/library/games"},
        }
