"""Pure normalizers for a media item's remote images and trailers.

Extracted from the (very large) ``api/v1/media.py`` router: these functions
have no request/router dependencies — they turn the loosely-typed
``extra_data`` blobs (provider results, remote images, trailers) into the
clean shapes the image/trailer endpoints return. Kept together so the router
module carries endpoints, not blob-parsing.
"""

from datetime import UTC, datetime
from typing import Literal

from streamarr.models.media import MediaItem
from streamarr.utils.extra_data import load_extra_data

# Poster/backdrop discriminator (mirrors the router's alias).
ImageType = Literal["poster", "backdrop"]


def _normalize_remote_image(raw: dict) -> dict | None:
    image_type = raw.get("image_type") or raw.get("type")
    url = raw.get("url") or raw.get("path")
    provider_id = raw.get("provider_id") or raw.get("id") or raw.get("guid") or url
    if image_type not in {"poster", "backdrop"}:
        return None
    if not isinstance(url, str) or not url.strip():
        return None

    provider = raw.get("provider") if isinstance(raw.get("provider"), str) else "metadata"
    thumbnail_url = raw.get("thumbnail_url")
    if not isinstance(thumbnail_url, str):
        thumbnail_url = raw.get("thumbnail") if isinstance(raw.get("thumbnail"), str) else None

    score = raw.get("score")
    if not isinstance(score, (int, float)):
        score = None
    width = raw.get("width")
    if not isinstance(width, int):
        width = None
    height = raw.get("height")
    if not isinstance(height, int):
        height = None
    language = raw.get("language") if isinstance(raw.get("language"), str) else None

    return {
        "provider": provider.strip(),
        "provider_id": str(provider_id),
        "image_type": image_type,
        "url": url.strip(),
        "thumbnail_url": thumbnail_url,
        "width": width,
        "height": height,
        "language": language,
        "score": score,
    }


def _remote_image_candidates(media_item: MediaItem) -> list[dict]:
    extra_data = load_extra_data(media_item)
    candidates: list[dict] = []
    for key in ("remote_images", "image_provider_results"):
        raw_candidates = extra_data.get(key)
        if isinstance(raw_candidates, list):
            candidates.extend(raw for raw in raw_candidates if isinstance(raw, dict))

    if media_item.poster_path:
        candidates.append(
            {"provider": "current", "id": "poster", "type": "poster", "url": media_item.poster_path}
        )
    if media_item.backdrop_path:
        candidates.append(
            {"provider": "current", "id": "backdrop", "type": "backdrop", "url": media_item.backdrop_path}
        )

    normalized = [_normalize_remote_image(raw) for raw in candidates]
    return [candidate for candidate in normalized if candidate is not None]


def _parse_datetime(value) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def _normalize_trailer(raw: dict) -> dict | None:
    url = raw.get("url") or raw.get("path") or raw.get("uri")
    provider_id = raw.get("provider_id") or raw.get("id") or raw.get("key") or url
    name = raw.get("name") or raw.get("title") or "Trailer"
    trailer_type = (raw.get("type") or raw.get("video_type") or "trailer").lower()
    if trailer_type not in {"trailer", "teaser", "clip"}:
        return None
    if not isinstance(url, str) or not url.strip():
        site = raw.get("site") if isinstance(raw.get("site"), str) else None
        key = raw.get("key") if isinstance(raw.get("key"), str) else None
        if site and key and site.lower() == "youtube":
            url = f"https://www.youtube.com/watch?v={key}"
        else:
            return None

    provider = raw.get("provider") if isinstance(raw.get("provider"), str) else "metadata"
    site = raw.get("site") if isinstance(raw.get("site"), str) else None
    language = raw.get("language") or raw.get("iso_639_1")
    if not isinstance(language, str):
        language = None
    official = raw.get("official")
    if not isinstance(official, bool):
        official = None

    return {
        "id": str(provider_id),
        "name": str(name),
        "url": url.strip(),
        "provider": provider.strip() or "metadata",
        "provider_id": str(provider_id) if provider_id is not None else None,
        "site": site,
        "language": language,
        "official": official,
        "published_at": _parse_datetime(raw.get("published_at") or raw.get("published_date")),
    }


def _trailer_candidates(media_item: MediaItem) -> list[dict]:
    extra_data = load_extra_data(media_item)
    candidates: list[dict] = []
    for key in ("trailers", "remote_trailers", "video_provider_results", "videos"):
        raw_candidates = extra_data.get(key)
        if isinstance(raw_candidates, list):
            candidates.extend(raw for raw in raw_candidates if isinstance(raw, dict))

    normalized = [_normalize_trailer(raw) for raw in candidates]
    deduped: dict[tuple[str, str], dict] = {}
    for candidate in normalized:
        if candidate is None:
            continue
        deduped[(candidate["provider"].lower(), candidate["id"])] = candidate
    return list(deduped.values())


def _find_remote_image(
    media_item: MediaItem,
    *,
    image_type: ImageType,
    provider: str,
    provider_id: str,
) -> dict | None:
    provider_key = provider.strip().lower()
    provider_id_key = provider_id.strip()
    for candidate in _remote_image_candidates(media_item):
        if (
            candidate["image_type"] == image_type
            and candidate["provider"].lower() == provider_key
            and candidate["provider_id"] == provider_id_key
        ):
            return candidate
    return None


def _image_language_matches(
    candidate: dict,
    *,
    language: str | None,
    include_language_neutral: bool,
) -> bool:
    if not language:
        return True

    candidate_language = candidate.get("language")
    if not candidate_language:
        return include_language_neutral
    return str(candidate_language).casefold() == language.casefold()
