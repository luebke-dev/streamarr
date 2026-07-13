"""Game library plugin."""

import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any

from streamarr.libraries.base import LibraryBase

logger = logging.getLogger(__name__)

# Retro console ROM extensions the streamarr-retro (libretro) container can boot.
# Deliberately distinct from the PC-installer extensions (.exe/.msi/.iso) — a
# retro ROM is a first-class launchable game, a PC installer is not.
# ROM extensions live in game_platforms (the single source, derived from the
# extension→platform map). Imported lazily inside methods below — a top-level
# import would pull the eager `streamarr.services` package init and cycle back
# into this module during library registration.
def _rom_extensions() -> frozenset[str]:
    from streamarr.services.game_platforms import ROM_EXTENSIONS

    return ROM_EXTENSIONS

# no-intro / TOSEC region + dump tags to strip for a clean display title,
# e.g. "Super Mario World (USA) [!].sfc" -> "Super Mario World".
_ROM_TAG_RE = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]")


def _clean_rom_title(filename: str) -> str:
    """Derive a human title from a ROM filename (strip extension + region tags)."""
    stem = Path(filename).stem
    stem = _ROM_TAG_RE.sub("", stem)
    stem = stem.replace("_", " ").strip()
    return re.sub(r"\s{2,}", " ", stem) or Path(filename).stem

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
        """Score a game release.

        Platform scoring is derived from the RAW release title (not the
        PC-defaulted ``metadata['platform']``) so a native console ROM — which
        streamarr can actually run in the retro container — is preferred over an
        unofficial PC port. An untagged title (typical no-intro ROM name) is
        treated as a likely ROM and ranked above PC.
        """
        from streamarr.services.game_platforms import (
            is_retro_platform,
            platform_from_release_title,
        )

        score = 0.0

        # Platform scoring (0-30). Prefer emulatable-here console ROMs.
        rel_platform = platform_from_release_title(
            metadata.get("original_title") or metadata.get("title") or ""
        )
        if is_retro_platform(rel_platform):
            score += 30  # native ROM we can boot in streamarr-retro
        elif rel_platform is None:
            score += 22  # untagged (likely a no-intro ROM) — favour over PC
        elif rel_platform == "pc":
            score += 18  # PC/PC-port — streamable, but not the native ROM
        else:
            score += 8  # modern console we can't emulate here

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

    async def get_supported_extensions(self) -> list[str]:
        """Retro ROM extensions this library ingests."""
        return sorted(_rom_extensions())

    async def extract_metadata_from_filename(self, filename: str) -> dict[str, Any]:
        """Parse a clean title (+ platform hint) from a ROM filename."""
        platform_match = _PLATFORM_RE.search(filename)
        return {
            "title": _clean_rom_title(filename),
            "platform": platform_match.group(1) if platform_match else None,
        }

    async def scan_library(self, path: str) -> list[dict[str, Any]]:
        """Scan the games library path for retro ROM files.

        Returns one dict per ROM (same shape as the movie scanner —
        ``path``/``filename``/``size``/``extension`` plus a parsed ``title``
        and ``platform``). Persistence into MediaItem/MediaFile happens in
        ``LibraryService.scan_library_for_media`` (games are ingested, not just
        discovered).
        """
        discovered: list[dict[str, Any]] = []
        try:
            path_obj = Path(path)
            if not path_obj.exists():
                logger.warning("Game library path does not exist: %s", path)
                return discovered

            for file_path in path_obj.rglob("*"):
                if not file_path.is_file():
                    continue
                if file_path.suffix.lower() not in _rom_extensions():
                    continue
                file_info: dict[str, Any] = {
                    "path": str(file_path),
                    "filename": file_path.name,
                    "size": file_path.stat().st_size,
                    "extension": file_path.suffix.lower(),
                }
                file_info.update(await self.extract_metadata_from_filename(file_path.name))
                discovered.append(file_info)

            logger.info("Found %s ROM files in %s", len(discovered), path)

        except Exception as e:
            logger.error("Error scanning game library %s: %s", path, e)

        return discovered

    @staticmethod
    def stamp_retro_profile(media_item: Any, platform: str | None = None) -> None:
        """Ensure the item launches via the retro container profile.

        Merges ``extra_data.lightrays.profile = "retro"`` (and an optional
        ``platform`` hint) WITHOUT clobbering any other ``extra_data`` /
        ``lightrays`` keys. The launch resolver keys off this to pick the retro
        profile and auto-derive the ROM bind mount from the game's MediaFile.
        A fresh dict is assigned so SQLAlchemy tracks the JSON change.
        """
        raw = media_item.extra_data
        data = dict(raw) if isinstance(raw, dict) else {}
        lr_raw = data.get("lightrays")
        lightrays = dict(lr_raw) if isinstance(lr_raw, dict) else {}
        lightrays["profile"] = "retro"
        data["lightrays"] = lightrays
        if platform:
            data.setdefault("platform", platform)
        media_item.extra_data = data

    async def handle_completed_download(
        self,
        *,
        download_context: dict[str, Any],
        files: list[Any],
        db: Any,
    ) -> dict[str, Any]:
        """Import a completed ROM download into the games library.

        Unlike the movie importer (which registers huge files in-place on an
        rclone mount), ROMs are tiny, so we COPY each ROM into the games
        library (``/library/games/imported``) and register the file at its
        library path. That keeps every game a first-class library file and —
        crucially — puts it under the games-library root the launch resolver
        translates to a host bind mount, so a downloaded game is immediately
        launchable in the retro container.
        """
        import shutil

        from streamarr.models.media import AvailabilityStatus, MediaFile

        media_item = download_context["media_item"]

        library_root = Path(await self.get_default_path())
        dest_dir = library_root / "imported"

        files_imported = 0
        for raw_file in files:
            file = Path(raw_file)
            if file.suffix.lower() not in _rom_extensions():
                continue
            if not file.exists():
                logger.warning("Game %s: download file missing: %s", media_item.title, file)
                continue

            # Copy into the library unless the file already lives there (e.g. a
            # torrent that downloaded straight into the games library).
            try:
                already_in_library = file.resolve().is_relative_to(library_root.resolve())
            except (OSError, ValueError):
                already_in_library = False

            if already_in_library:
                dest = file
            else:
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = dest_dir / file.name
                shutil.copy2(file, dest)
                logger.info("Imported ROM into games library: %s -> %s", file, dest)

            media_file = MediaFile(
                guid=uuid.uuid4(),
                media_item_guid=media_item.guid,
                file_path=str(dest),
                file_name=dest.name,
                file_size=dest.stat().st_size if dest.exists() else None,
                format=dest.suffix.lstrip("."),
            )
            db.add(media_file)
            files_imported += 1

        if files_imported == 0:
            logger.error(
                "Game %s: completed download had no ROM files", media_item.title
            )
            return {"success": False, "error": "No ROM files in completed download"}

        self.stamp_retro_profile(media_item)
        media_item.availability_status = AvailabilityStatus.AVAILABLE
        await db.commit()

        return {
            "success": True,
            "files_imported": files_imported,
            "game_title": media_item.title,
        }

    def get_settings_schema(self) -> dict[str, Any]:
        return {
            "enable_library": {"default": True, "key": "enabled"},
            "library_path": {"default": "/library/games"},
        }
