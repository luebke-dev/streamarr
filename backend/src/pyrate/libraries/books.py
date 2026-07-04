"""Unified Books library plugin — ebooks and audiobooks.

Handles both ebooks (.epub, .pdf, .mobi, …) and audiobooks (.m4b, .mp3, …)
as a single library.  The hierarchy is flat: each BOOKS item is one title.
Audiobook chapters are tracked as AUDIOBOOK_CHAPTERS children.
"""

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any

from pyrate.libraries.base import LibraryBase
from pyrate.parsers.release_parser import ReleaseParser

logger = logging.getLogger(__name__)

EBOOK_EXTENSIONS = {
    ".epub", ".pdf", ".mobi", ".azw", ".azw3",
    ".cbz", ".cbr", ".cb7", ".cbt", ".djvu", ".fb2", ".lit", ".txt",
}
AUDIOBOOK_EXTENSIONS = {
    ".m4b", ".m4a", ".mp3", ".aax", ".aa",
    ".flac", ".ogg", ".opus", ".wma", ".aac",
}
ALL_EXTENSIONS = EBOOK_EXTENSIONS | AUDIOBOOK_EXTENSIONS


class BookLibraryPlugin(LibraryBase):
    """Plugin for managing books — ebooks and audiobooks in one library."""

    def get_name(self) -> str:
        return "Book Library"

    def get_library_type(self) -> str:
        return "BOOKS"

    def get_media_item_types(self) -> list[dict[str, Any]]:
        return [
            {"name": "AUTHORS", "label": "Author", "parent_type": None},
            {"name": "BOOKS", "label": "Book", "parent_type": "AUTHORS"},
            {"name": "AUDIOBOOK_CHAPTERS", "label": "Chapter", "parent_type": "BOOKS"},
        ]

    async def get_default_path(self) -> str:
        return "/library/books"

    async def validate_path(self, path: str) -> bool:
        try:
            p = Path(path)
            if p.exists():
                return p.is_dir()
            return p.parent.exists() and os.access(p.parent, os.W_OK)
        except Exception as e:
            logger.error("Error validating book library path %s: %s", path, e)
            return False

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    async def get_library_stats(self, path: str) -> dict[str, Any]:
        stats: dict[str, Any] = {
            "path": path,
            "file_count": 0,
            "total_size": 0,
            "ebook_count": 0,
            "audiobook_count": 0,
            "file_types": {},
        }
        try:
            p = Path(path)
            if not p.exists():
                return stats
            for f in p.rglob("*"):
                if not f.is_file():
                    continue
                ext = f.suffix.lower()
                if ext not in ALL_EXTENSIONS:
                    continue
                stats["file_count"] += 1
                stats["total_size"] += f.stat().st_size
                stats["file_types"][ext] = stats["file_types"].get(ext, 0) + 1
                if ext in EBOOK_EXTENSIONS:
                    stats["ebook_count"] += 1
                else:
                    stats["audiobook_count"] += 1
        except Exception as e:
            logger.error("Error getting book library stats: %s", e)
        return stats

    # ------------------------------------------------------------------
    # File handling
    # ------------------------------------------------------------------

    async def get_supported_extensions(self) -> list[str]:
        return sorted(ALL_EXTENSIONS)

    async def validate_media_file(self, file_path: str) -> bool:
        return Path(file_path).suffix.lower() in ALL_EXTENSIONS

    async def scan_library(self, path: str) -> list[dict[str, Any]]:
        """Scan for books.  Each subdirectory with matching files is one item."""
        items: list[dict[str, Any]] = []
        p = Path(path)
        if not p.exists():
            return items

        # Group by parent directory
        dirs: dict[str, list[Path]] = {}
        for f in p.rglob("*"):
            if f.is_file() and f.suffix.lower() in ALL_EXTENSIONS:
                key = str(f.parent)
                dirs.setdefault(key, []).append(f)

        for dir_path, files in dirs.items():
            title = Path(dir_path).name
            has_audio = any(f.suffix.lower() in AUDIOBOOK_EXTENSIONS for f in files)
            items.append({
                "path": dir_path,
                "title": title,
                "type": "audiobook" if has_audio else "ebook",
                "files": [{"path": str(f), "name": f.name} for f in sorted(files)],
            })
        return items

    # ------------------------------------------------------------------
    # Release metadata & scoring
    # ------------------------------------------------------------------

    async def extract_release_metadata(self, release_title: str) -> dict[str, Any]:
        """Parse a book release title for format, quality, etc."""
        title_lower = release_title.lower()

        # Detect format
        book_format = "unknown"
        if any(ext in title_lower for ext in (".epub", "epub")):
            book_format = "epub"
        elif any(ext in title_lower for ext in (".pdf", "pdf")):
            book_format = "pdf"
        elif any(ext in title_lower for ext in (".mobi", "mobi", ".azw")):
            book_format = "mobi"
        elif any(ext in title_lower for ext in (".m4b", "m4b", "audiobook")):
            book_format = "audiobook"
        elif any(ext in title_lower for ext in (".mp3", "mp3")):
            book_format = "mp3_audiobook"
        elif any(ext in title_lower for ext in (".cbz", ".cbr", "comic")):
            book_format = "comic"

        # Detect language
        languages = ReleaseParser.extract_languages(release_title)

        # Detect if retail/scan
        is_retail = any(kw in title_lower for kw in ("retail", "official", "hq"))
        is_scan = any(kw in title_lower for kw in ("scan", "ocr"))

        return {
            "original_title": release_title,
            "format": book_format,
            "languages": languages,
            "is_retail": is_retail,
            "is_scan": is_scan,
            "release_group": ReleaseParser.extract_release_group(release_title),
        }

    async def score_release(
        self, metadata: dict[str, Any], preferences: dict[str, Any] | None = None
    ) -> float:
        """Score a book release 0-100."""
        score = 50.0
        fmt = metadata.get("format", "unknown")

        # Format scoring
        format_scores = {
            "epub": 25.0,
            "audiobook": 20.0,
            "mp3_audiobook": 15.0,
            "pdf": 10.0,
            "mobi": 8.0,
            "comic": 12.0,
            "unknown": 0.0,
        }
        score += format_scores.get(fmt, 0.0)

        # Quality bonuses
        if metadata.get("is_retail"):
            score += 10.0
        if metadata.get("is_scan"):
            score -= 15.0

        # Language matching
        languages = metadata.get("languages", [])
        if "de" in languages or "german" in [l.lower() for l in languages]:
            score += 10.0
        if "en" in languages or "english" in [l.lower() for l in languages]:
            score += 5.0

        return max(0.0, min(100.0, score))

    # ------------------------------------------------------------------
    # Naming
    # ------------------------------------------------------------------

    def get_naming_schema(self) -> dict[str, Any]:
        return {
            "variables": [
                {"name": "author", "description": "Book author"},
                {"name": "title", "description": "Book title"},
                {"name": "year", "description": "Publication year"},
            ],
            "defaults": {
                "author_folder": "{author}",
                "book_file": "{author} - {title}",
            },
            "options": {
                "replace_illegal_characters": True,
                "colon_replacement": " -",
            },
        }

    def get_settings_schema(self) -> dict[str, Any]:
        return {
            "enable_library": {"default": True, "key": "enabled"},
            "library_path": {"default": "/library/books"},
            "enable_on_demand_downloads": {"default": True},
        }

    def get_preview_data(self) -> dict[str, Any]:
        return {
            "author": "Frank Herbert",
            "title": "Dune",
            "year": 1965,
        }

    def get_library_icon(self) -> str:
        return "mdi-book-open-page-variant"

    def get_item_icon(self) -> str:
        return "mdi-book"

    def get_play_button_icon(self) -> str:
        return "mdi-book-open-variant"

    def get_play_button_label(self) -> str:
        return "common.read"

    def get_metadata_provider(self) -> str | None:
        return "openlibrary"

    # ------------------------------------------------------------------
    # Probing
    # ------------------------------------------------------------------

    async def probe_media_file(self, file_path: str) -> dict[str, Any]:
        """Extract metadata from book file."""
        p = Path(file_path)
        ext = p.suffix.lower()
        result: dict[str, Any] = {
            "file_path": file_path,
            "format": ext.lstrip("."),
            "file_size": p.stat().st_size if p.exists() else 0,
        }

        if ext in AUDIOBOOK_EXTENSIONS:
            result["is_audiobook"] = True
            # ffprobe for audio metadata — run as an async subprocess so the
            # (up to 30s) probe never blocks the event loop during a scan.
            try:
                import asyncio

                proc = await asyncio.create_subprocess_exec(
                    "ffprobe", "-v", "quiet",
                    "-print_format", "json",
                    "-show_format", "-show_streams",
                    file_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                try:
                    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
                except (TimeoutError, asyncio.TimeoutError):
                    proc.kill()
                    await proc.communicate()
                    raise
                if proc.returncode == 0:
                    data = json.loads(stdout.decode("utf-8", errors="replace"))
                    fmt = data.get("format", {})
                    result["duration"] = float(fmt.get("duration", 0))
                    result["bitrate"] = int(fmt.get("bit_rate", 0))
                    result["codec"] = fmt.get("format_name", "")
                    tags = fmt.get("tags", {})
                    if tags.get("title"):
                        result["title"] = tags["title"]
                    if tags.get("artist") or tags.get("author"):
                        result["author"] = tags.get("artist") or tags.get("author")
            except Exception as e:
                logger.debug("ffprobe failed for %s: %s", file_path, e)

        elif ext == ".epub":
            result["is_audiobook"] = False
            try:
                import zipfile
                with zipfile.ZipFile(file_path) as zf:
                    # Read OPF for metadata
                    for name in zf.namelist():
                        if name.endswith(".opf"):
                            opf = zf.read(name).decode("utf-8", errors="replace")
                            # Simple XML parsing for title/author
                            import re
                            title_match = re.search(r"<dc:title[^>]*>([^<]+)</dc:title>", opf)
                            creator_match = re.search(r"<dc:creator[^>]*>([^<]+)</dc:creator>", opf)
                            if title_match:
                                result["title"] = title_match.group(1)
                            if creator_match:
                                result["author"] = creator_match.group(1)
                            break
            except Exception as e:
                logger.debug("EPUB metadata extraction failed for %s: %s", file_path, e)

        else:
            result["is_audiobook"] = False

        return result
