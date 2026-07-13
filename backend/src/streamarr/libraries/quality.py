"""Canonical quality ladders + release/file quality parsing.

Sonarr/Radarr-style quality model: every media kind has an *ordered* list of
qualities (lowest -> highest). A :class:`QualityProfile` (see
``schemas/scoring.py`` / ``services/quality_profile.py``) is a subset of one
ladder with an ``allowed`` flag per rung plus a ``cutoff`` rung. This module
is pure (no DB / no I/O) so it is cheap to call and trivial to unit test.

``parse_quality`` maps the metadata dict produced by a library plugin's
``extract_release_metadata`` (or a probed ``MediaFile``) onto a ladder rung.
The returned ``QualityInfo`` carries the canonical rung id, its default rank
(index in the ladder, higher = better) and a ``revision`` (proper/repack)
so a same-rung proper can still be treated as an upgrade.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class QualityKind(str, Enum):
    VIDEO = "video"
    AUDIO = "audio"
    BOOK = "book"
    AUDIOBOOK = "audiobook"
    GAME = "game"


@dataclass(frozen=True)
class QualityDef:
    """A single rung on a canonical ladder."""

    id: str
    label: str
    kind: QualityKind


@dataclass(frozen=True)
class QualityInfo:
    """Result of parsing a release/file onto a ladder."""

    id: str
    label: str
    kind: QualityKind
    rank: int  # default position in the canonical ladder (higher = better)
    revision: int = 0  # 0 normal, 1 repack, 2 proper (tiebreak within a rung)


# --------------------------------------------------------------------------- #
# Canonical ladders (lowest -> highest). Rank = list index.
# --------------------------------------------------------------------------- #

def _ladder(kind: QualityKind, rungs: list[tuple[str, str]]) -> list[QualityDef]:
    return [QualityDef(rid, label, kind) for rid, label in rungs]


_VIDEO_LADDER = _ladder(
    QualityKind.VIDEO,
    [
        ("unknown", "Unknown"),
        ("cam", "CAM"),
        ("telesync", "TeleSync"),
        ("telecine", "TeleCine"),
        ("screener", "Screener"),
        ("dvd", "DVD"),
        ("sdtv", "SDTV"),
        ("hdtv-720p", "HDTV-720p"),
        ("webrip-720p", "WEBRip-720p"),
        ("webdl-720p", "WEB-DL-720p"),
        ("bluray-720p", "Bluray-720p"),
        ("hdtv-1080p", "HDTV-1080p"),
        ("webrip-1080p", "WEBRip-1080p"),
        ("webdl-1080p", "WEB-DL-1080p"),
        ("bluray-1080p", "Bluray-1080p"),
        ("remux-1080p", "Bluray-1080p Remux"),
        ("hdtv-2160p", "HDTV-2160p"),
        ("webrip-2160p", "WEBRip-2160p"),
        ("webdl-2160p", "WEB-DL-2160p"),
        ("bluray-2160p", "Bluray-2160p"),
        ("remux-2160p", "Bluray-2160p Remux"),
    ],
)

_AUDIO_LADDER = _ladder(
    QualityKind.AUDIO,
    [
        ("unknown", "Unknown"),
        ("mp3-low", "MP3 (<256)"),
        ("mp3-high", "MP3 320 / V0"),
        ("lossy-aac", "AAC / lossy"),
        ("lossless", "Lossless (FLAC)"),
        ("lossless-hires", "Lossless Hi-Res"),
    ],
)

_BOOK_LADDER = _ladder(
    QualityKind.BOOK,
    [
        ("unknown", "Unknown"),
        ("scan", "Scan / OCR"),
        ("pdf", "PDF"),
        ("comic", "Comic (CBZ/CBR)"),
        ("mobi", "MOBI / AZW"),
        ("epub", "EPUB"),
        ("retail", "Retail EPUB"),
    ],
)

_AUDIOBOOK_LADDER = _ladder(
    QualityKind.AUDIOBOOK,
    [
        ("unknown", "Unknown"),
        ("mp3-audiobook", "MP3 Audiobook"),
        ("m4b-audiobook", "M4B Audiobook"),
    ],
)

_GAME_LADDER = _ladder(
    QualityKind.GAME,
    [
        ("standard", "Standard"),
    ],
)

_LADDERS: dict[QualityKind, list[QualityDef]] = {
    QualityKind.VIDEO: _VIDEO_LADDER,
    QualityKind.AUDIO: _AUDIO_LADDER,
    QualityKind.BOOK: _BOOK_LADDER,
    QualityKind.AUDIOBOOK: _AUDIOBOOK_LADDER,
    QualityKind.GAME: _GAME_LADDER,
}

_RANK_BY_ID: dict[QualityKind, dict[str, int]] = {
    kind: {d.id: i for i, d in enumerate(defs)} for kind, defs in _LADDERS.items()
}
_DEF_BY_ID: dict[QualityKind, dict[str, QualityDef]] = {
    kind: {d.id: d for d in defs} for kind, defs in _LADDERS.items()
}


# --------------------------------------------------------------------------- #
# media_type -> ladder kind
# --------------------------------------------------------------------------- #

_VIDEO_TYPES = {"MOVIES", "SHOWS", "SEASONS", "EPISODES"}
_AUDIO_TYPES = {"MUSIC", "ARTISTS", "ALBUMS", "SONGS"}
_GAME_TYPES = {"GAMES"}
# BOOKS/AUDIOBOOKS are disambiguated by the parsed ``format``.
_BOOK_TYPES = {"BOOKS", "AUDIOBOOKS", "AUDIOBOOK_CHAPTERS"}


def kind_for_media_type(media_type: Any) -> QualityKind:
    """Map a MediaType (enum or str) to its quality ladder kind."""
    name = getattr(media_type, "value", media_type)
    name = str(name or "").upper()
    if name in _VIDEO_TYPES:
        return QualityKind.VIDEO
    if name in _AUDIO_TYPES:
        return QualityKind.AUDIO
    if name in _GAME_TYPES:
        return QualityKind.GAME
    # default for books; audiobook split happens in parse_quality via format
    return QualityKind.BOOK


def qualities_for_media_type(media_type: Any) -> list[QualityDef]:
    """Canonical ordered ladder for a media type (for default profiles + UI).

    Books expose both the ebook and audiobook rungs (disjoint segments) so a
    single ``books`` profile can target either.
    """
    kind = kind_for_media_type(media_type)
    if kind is QualityKind.BOOK:
        # Single shared "unknown" catch-all; audiobook rungs append after it.
        # ``parse_quality`` never emits the audiobook "unknown" rung.
        return list(_BOOK_LADDER) + [
            d for d in _AUDIOBOOK_LADDER if d.id != "unknown"
        ]
    return list(_LADDERS[kind])


def quality_def(kind: QualityKind, quality_id: str) -> QualityDef | None:
    return _DEF_BY_ID.get(kind, {}).get(quality_id)


def canonical_rank(kind: QualityKind, quality_id: str) -> int:
    return _RANK_BY_ID.get(kind, {}).get(quality_id, 0)


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #

_RES_ALIASES = {"4320p": "2160p"}  # treat 8K as top video tier
_VIDEO_SOURCE_TO_PREFIX = {
    "remux": "remux",
    "bluray": "bluray",
    "web-dl": "webdl",
    "webdl": "webdl",
    "web": "webdl",
    "webrip": "webrip",
    "hdtv": "hdtv",
}


def _revision(metadata: dict[str, Any], title: str) -> int:
    t = title.lower()
    if metadata.get("is_proper") or "proper" in t:
        return 2
    if metadata.get("is_repack") or "repack" in t:
        return 1
    return 0


def _info(kind: QualityKind, quality_id: str, revision: int = 0) -> QualityInfo:
    d = _DEF_BY_ID[kind].get(quality_id) or _DEF_BY_ID[kind]["unknown"]
    return QualityInfo(
        id=d.id,
        label=d.label,
        kind=kind,
        rank=_RANK_BY_ID[kind][d.id],
        revision=revision,
    )


def _parse_video(metadata: dict[str, Any], title: str) -> QualityInfo:
    rev = _revision(metadata, title)
    source = str(metadata.get("source") or "").lower().strip()
    resolution = str(
        metadata.get("resolution") or metadata.get("quality") or ""
    ).lower().strip()
    resolution = _RES_ALIASES.get(resolution, resolution)
    is_remux = bool(metadata.get("is_remux")) or source == "remux"

    # Sourceless / low-quality theatrical rips first.
    if source in ("cam", "telesync", "telecine", "screener"):
        return _info(QualityKind.VIDEO, source, rev)
    if source == "dvd" and not resolution:
        return _info(QualityKind.VIDEO, "dvd", rev)

    if resolution in ("480p", "576p", "") and source in ("dvd", ""):
        if source == "dvd":
            return _info(QualityKind.VIDEO, "dvd", rev)

    if not resolution:
        # No resolution: best-effort by source only.
        if source in ("bluray",):
            return _info(QualityKind.VIDEO, "bluray-1080p", rev)
        if source == "dvd":
            return _info(QualityKind.VIDEO, "dvd", rev)
        if source in ("hdtv", "web-dl", "webdl", "web", "webrip"):
            return _info(QualityKind.VIDEO, "sdtv", rev)
        return _info(QualityKind.VIDEO, "unknown", rev)

    if resolution in ("480p", "576p"):
        return _info(QualityKind.VIDEO, "sdtv", rev)

    if resolution not in ("720p", "1080p", "2160p"):
        return _info(QualityKind.VIDEO, "unknown", rev)

    if is_remux and resolution in ("1080p", "2160p"):
        return _info(QualityKind.VIDEO, f"remux-{resolution}", rev)

    prefix = _VIDEO_SOURCE_TO_PREFIX.get(source)
    if prefix is None:
        # Unknown source but known resolution -> assume webdl tier.
        prefix = "webdl"
    rung = f"{prefix}-{resolution}"
    if rung not in _RANK_BY_ID[QualityKind.VIDEO]:
        # e.g. remux-720p doesn't exist -> fall back to bluray of that res.
        rung = f"bluray-{resolution}"
        if rung not in _RANK_BY_ID[QualityKind.VIDEO]:
            rung = "unknown"
    return _info(QualityKind.VIDEO, rung, rev)


def _parse_audio(metadata: dict[str, Any], title: str) -> QualityInfo:
    rev = _revision(metadata, title)
    fmt = str(metadata.get("format") or "").lower()
    bitrate = metadata.get("bitrate")
    try:
        bitrate = int(bitrate) if bitrate is not None else None
    except (TypeError, ValueError):
        bitrate = None
    t = title.lower()

    lossless = (
        fmt in ("flac", "alac", "wav", "ape", "wv")
        or any(k in t for k in ("flac", "alac", " wav", ".wav", "ape ", "lossless"))
    )
    if lossless:
        hires = any(
            k in t for k in ("24bit", "24-bit", "24bit", "hi-res", "hires", "96khz", "192khz", "24-96", "24-192")
        )
        return _info(
            QualityKind.AUDIO,
            "lossless-hires" if hires else "lossless",
            rev,
        )
    if fmt in ("aac", "m4a", "opus", "ogg", "vorbis") or any(
        k in t for k in (" aac", ".aac", "opus", "ogg", "m4a")
    ):
        return _info(QualityKind.AUDIO, "lossy-aac", rev)

    # MP3 / generic lossy: decide by bitrate / title cues.
    if bitrate is not None:
        kbps = bitrate // 1000 if bitrate > 10000 else bitrate
        if kbps >= 256:
            return _info(QualityKind.AUDIO, "mp3-high", rev)
        if kbps > 0:
            return _info(QualityKind.AUDIO, "mp3-low", rev)
    if any(k in t for k in ("320", "v0", "v 0", "320kbps", "cbr 320")):
        return _info(QualityKind.AUDIO, "mp3-high", rev)
    if any(k in t for k in ("128", "192", "v2", "v 2", "mp3")):
        return _info(QualityKind.AUDIO, "mp3-low", rev)
    return _info(QualityKind.AUDIO, "unknown", rev)


def _parse_book(metadata: dict[str, Any], title: str) -> QualityInfo:
    rev = _revision(metadata, title)
    fmt = str(metadata.get("format") or "").lower()
    if fmt in ("audiobook", "m4b"):
        return _info(QualityKind.AUDIOBOOK, "m4b-audiobook", rev)
    if fmt in ("mp3_audiobook",):
        return _info(QualityKind.AUDIOBOOK, "mp3-audiobook", rev)
    if metadata.get("is_scan"):
        return _info(QualityKind.BOOK, "scan", rev)
    if fmt == "pdf":
        return _info(QualityKind.BOOK, "pdf", rev)
    if fmt == "comic":
        return _info(QualityKind.BOOK, "comic", rev)
    if fmt == "mobi":
        return _info(QualityKind.BOOK, "mobi", rev)
    if fmt == "epub":
        return _info(
            QualityKind.BOOK, "retail" if metadata.get("is_retail") else "epub", rev
        )
    return _info(QualityKind.BOOK, "unknown", rev)


def parse_quality(
    metadata: dict[str, Any] | None,
    *,
    media_type: Any = None,
    title: str | None = None,
) -> QualityInfo:
    """Map plugin release metadata (or probed file info) to a ladder rung.

    ``metadata`` is the dict from ``extract_release_metadata`` (video/book) or
    a dict assembled from a ``MediaFile`` (``format``/``bitrate``). ``title``
    (release title) is used as a fallback for audio where plugins don't emit
    structured metadata. Unknown input degrades to the ``unknown`` rung.
    """
    metadata = metadata or {}
    title = title or str(metadata.get("original_title") or "")
    kind = kind_for_media_type(media_type) if media_type is not None else None

    if kind is None:
        # Infer: a ``format`` key means book/audio; ``resolution`` means video.
        if metadata.get("resolution") or metadata.get("source"):
            kind = QualityKind.VIDEO
        elif metadata.get("format") in ("epub", "pdf", "mobi", "comic", "audiobook", "mp3_audiobook"):
            kind = QualityKind.BOOK
        else:
            kind = QualityKind.AUDIO

    if kind is QualityKind.VIDEO:
        return _parse_video(metadata, title)
    if kind is QualityKind.AUDIO:
        return _parse_audio(metadata, title)
    if kind is QualityKind.GAME:
        return _info(QualityKind.GAME, "standard", _revision(metadata, title))
    # BOOK kind covers both ebook and audiobook rungs.
    return _parse_book(metadata, title)
