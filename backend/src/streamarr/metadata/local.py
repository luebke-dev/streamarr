"""Safe local NFO and artwork discovery for library scans.

This is a Streamarr-native provider contract. It intentionally implements the
widely used Kodi/Jellyfin file conventions without depending on Jellyfin code.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from streamarr.metadata.base import MetadataBase

_MAX_NFO_BYTES = 2 * 1024 * 1024
_PROVIDER_ID_RE = re.compile(
    r"\[(?P<provider>tmdb|tvdb|imdb)id-(?P<value>[^\]]+)\]", re.IGNORECASE
)
_LOCK_FIELD_MAP = {
    "name": "title",
    "title": "title",
    "originaltitle": "original_title",
    "overview": "description",
    "plot": "description",
    "tagline": "tagline",
    "premieredate": "release_date",
    "releasedate": "release_date",
    "officialrating": "content_rating",
    "images": "poster_path",
}


@dataclass(slots=True)
class LocalMetadata:
    values: dict[str, Any] = field(default_factory=dict)
    external_ids: dict[str, str] = field(default_factory=dict)
    locked_fields: set[str] = field(default_factory=set)
    poster_path: Path | None = None
    backdrop_path: Path | None = None
    source_path: Path | None = None


def provider_ids_from_name(value: str) -> dict[str, str]:
    return {
        match.group("provider").lower(): match.group("value").strip()
        for match in _PROVIDER_ID_RE.finditer(value)
    }


def clean_provider_ids(value: str) -> str:
    return re.sub(r"\s+", " ", _PROVIDER_ID_RE.sub("", value)).strip()


def _first_text(root: ET.Element, *names: str) -> str | None:
    for name in names:
        element = root.find(name)
        if element is not None and element.text and element.text.strip():
            return element.text.strip()
    return None


def _nfo_candidates(media_path: Path, library_type: str) -> list[Path]:
    candidates = [media_path.with_suffix(".nfo")]
    if library_type.upper() == "MOVIES":
        candidates.append(media_path.parent / "movie.nfo")
    elif library_type.upper() == "SHOWS":
        candidates.extend(
            [media_path.parent / "episode.nfo", media_path.parent.parent / "tvshow.nfo"]
        )
    return list(dict.fromkeys(candidates))


def _find_artwork(directory: Path, stems: tuple[str, ...]) -> Path | None:
    for stem in stems:
        for extension in (".jpg", ".jpeg", ".png", ".webp", ".avif"):
            candidate = directory / f"{stem}{extension}"
            if candidate.is_file():
                return candidate
    return None


def read_local_metadata(media_path: Path, library_type: str) -> LocalMetadata:
    result = LocalMetadata(external_ids=provider_ids_from_name(str(media_path)))
    nfo = next((path for path in _nfo_candidates(media_path, library_type) if path.is_file()), None)
    if nfo is not None:
        try:
            raw = nfo.read_bytes()
            if len(raw) <= _MAX_NFO_BYTES and b"<!DOCTYPE" not in raw.upper():
                root = ET.fromstring(raw)
                mapping = {
                    "title": ("title", "name", "localtitle"),
                    "original_title": ("originaltitle",),
                    "description": ("plot", "outline", "review"),
                    "tagline": ("tagline",),
                    "content_rating": ("mpaa", "customrating"),
                    "year": ("year",),
                    "release_date": ("premiered", "releasedate", "aired"),
                }
                for target, names in mapping.items():
                    value = _first_text(root, *names)
                    if value:
                        result.values[target] = value

                for unique_id in root.findall("uniqueid"):
                    provider = (unique_id.attrib.get("type") or "").lower()
                    if provider and unique_id.text and unique_id.text.strip():
                        result.external_ids[provider] = unique_id.text.strip()
                for provider in ("tmdb", "tvdb", "imdb"):
                    value = _first_text(root, f"{provider}id", f"{provider}_id")
                    if value:
                        result.external_ids[provider] = value

                locked = _first_text(root, "lockedfields")
                if locked:
                    result.locked_fields.update(
                        _LOCK_FIELD_MAP.get(part.strip().lower(), part.strip().lower())
                        for part in re.split(r"[,|]", locked)
                        if part.strip()
                    )
                if (_first_text(root, "lockdata") or "").lower() in {"true", "1", "yes"}:
                    result.locked_fields.update(result.values)
                result.source_path = nfo
        except (OSError, ET.ParseError):
            # A malformed optional sidecar must not make the physical scan fail.
            pass

    directory = media_path.parent
    result.poster_path = _find_artwork(directory, ("poster", "folder", "cover", media_path.stem + "-poster"))
    result.backdrop_path = _find_artwork(directory, ("backdrop", "fanart", "background", "art"))
    return result


class LocalMetadataProvider(MetadataBase):
    """Provider facade used by the existing metadata registry/admin UI."""

    async def search(self, query: str, **kwargs) -> list[dict[str, Any]]:
        return []

    async def get_details(self, media_id: str | int, **kwargs) -> dict[str, Any]:
        path = Path(str(media_id))
        metadata = read_local_metadata(path, str(kwargs.get("media_type") or "MOVIES"))
        return {**metadata.values, "external_ids": metadata.external_ids}

    @staticmethod
    def get_config_schema() -> dict[str, Any]:
        return {}
