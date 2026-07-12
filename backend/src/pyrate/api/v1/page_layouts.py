"""Page Layout API Endpoints - Admin-configurable page layouts."""

import hashlib
import json
import logging
import uuid
from typing import Any

import redis.asyncio as redis_async
from fastapi import (
    APIRouter,
    BackgroundTasks,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from redis.exceptions import RedisError
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from pyrate.api.dependencies import (
    CurrentSuperuser,
    CurrentUser,
    DatabaseSession,
    UserPermissionsDep,
)
from pyrate.api.v1.search import search_local_content
from pyrate.api.v1.suggestions import _summaries
from pyrate.api.v1.trailers import browse_trailers
from pyrate.config import settings
from pyrate.models.list import List, ListVisibility
from pyrate.models.media import MediaItem, MediaType
from pyrate.models.page_layout import PageLayout, PageSection, SectionType
from pyrate.schemas.page_layout import (
    PageLayoutCreate,
    PageLayoutRead,
    PageLayoutRenderedRead,
    PageLayoutSummary,
    PageLayoutUpdate,
    PageSectionCreate,
    PageSectionRead,
    PageSectionUpdate,
    ReorderSectionsRequest,
)
from pyrate.schemas.search import SearchRequest
from pyrate.services.cache_control import (
    RENDER_CACHE_PREFIX,
    RENDER_STALE_PREFIX,
    clear_rendered_layout_cache,
)
from pyrate.services.favorite import FavoriteService
from pyrate.services.list import ListService
from pyrate.services.media_access import (
    allowed_media_types_for_permissions,
    max_age_for_user,
)
from pyrate.services.media_visibility import visibility_conditions
from pyrate.services.observability import (
    observe_layout_render,
    record_layout_cache_event,
)
from pyrate.services.page_layout import PageLayoutService

logger = logging.getLogger(__name__)

router = APIRouter()

_LAYOUT_RENDER_CACHE_CONTROL = "private, max-age=60, stale-while-revalidate=600"
_RENDER_CACHE_TTL_SECONDS = 120
_RENDER_STALE_TTL_SECONDS = 1800
_TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p"
_MAX_RENDERED_ITEMS = 100

_LIST_ITEM_TYPE_TO_MEDIA_TYPE = {
    "MOVIE": "MOVIES",
    "SHOW": "SHOWS",
    "GAME": "GAMES",
    "EPISODE": "EPISODES",
    "MUSIC": "MUSIC",
    "BOOK": "BOOKS",
    "AUDIOBOOK": "AUDIOBOOKS",
}


def _json_dump(data: Any) -> str:
    return json.dumps(
        jsonable_encoder(data),
        sort_keys=True,
        separators=(",", ":"),
    )


def _media_type_enum(value: str | MediaType | None) -> MediaType | None:
    if value is None:
        return None
    if isinstance(value, MediaType):
        return value
    try:
        return MediaType[str(value).upper()]
    except (KeyError, ValueError):
        return None


def _clamped_limit(value: Any, default: int = 20, maximum: int = _MAX_RENDERED_ITEMS) -> int:
    try:
        return max(1, min(int(value or default), maximum))
    except (TypeError, ValueError):
        return default


def _section_type_value(section: PageSection) -> str:
    section_type = section.section_type
    return section_type.value if hasattr(section_type, "value") else str(section_type)


def _layout_cache_key(
    layout: PageLayout,
    scope: str,
    current_user,
    permissions,
) -> str:
    sections = [
        {
            "guid": str(section.guid),
            "updated_at": section.updated_at.isoformat() if section.updated_at else None,
            "order_index": section.order_index,
            "enabled": section.is_enabled,
        }
        for section in sorted(layout.sections or [], key=lambda item: item.order_index)
    ]
    token = {
        "scope": scope,
        "layout_guid": str(layout.guid),
        "layout_updated_at": layout.updated_at.isoformat() if layout.updated_at else None,
        "sections": sections,
        "user_guid": str(current_user.guid),
        "ui_language": getattr(current_user, "ui_language", None),
        "is_superuser": bool(getattr(current_user, "is_superuser", False)),
        "parental_max_age": getattr(current_user, "parental_max_age", None),
        "allowed_libraries": sorted(getattr(permissions, "allowed_libraries", []) or []),
    }
    return hashlib.sha256(_json_dump(token).encode("utf-8")).hexdigest()


def _payload_etag(payload: dict[str, Any]) -> str:
    return f'"{hashlib.sha256(_json_dump(payload).encode("utf-8")).hexdigest()}"'


# The rendered-layout endpoints are the hottest path (home page for every
# user/media-type). Reuse one connection-pool-backed client across requests
# rather than opening and tearing down a fresh Redis connection on every cache
# read/write. On a connection error the client is dropped so the next call
# rebuilds it.
_render_redis_client: redis_async.Redis | None = None


def _get_render_redis() -> redis_async.Redis:
    global _render_redis_client
    if _render_redis_client is None:
        _render_redis_client = redis_async.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _render_redis_client


async def _reset_render_redis() -> None:
    global _render_redis_client
    client, _render_redis_client = _render_redis_client, None
    if client is not None:
        try:
            await client.aclose()
        except Exception:
            pass


async def _read_render_cache(prefix: str, key: str) -> dict[str, Any] | None:
    try:
        raw = await _get_render_redis().get(f"{prefix}{key}")
        if not raw:
            return None
        return json.loads(raw)
    except ValueError as exc:
        logger.debug("Failed to read page layout render cache: %s", exc)
        return None
    except RedisError as exc:
        logger.debug("Failed to read page layout render cache: %s", exc)
        await _reset_render_redis()
        return None


async def _write_render_cache(key: str, payload: dict[str, Any], etag: str) -> None:
    data = _json_dump({"payload": payload, "etag": etag})
    try:
        client = _get_render_redis()
        await client.setex(
            f"{RENDER_CACHE_PREFIX}{key}",
            _RENDER_CACHE_TTL_SECONDS,
            data,
        )
        await client.setex(
            f"{RENDER_STALE_PREFIX}{key}",
            _RENDER_STALE_TTL_SECONDS,
            data,
        )
    except RedisError as exc:
        logger.debug("Failed to write page layout render cache: %s", exc)
        await _reset_render_redis()


def _render_headers(etag: str, status_value: str) -> dict[str, str]:
    return {
        "Cache-Control": _LAYOUT_RENDER_CACHE_CONTROL,
        "ETag": etag,
        "X-Pyrate-Layout-Cache": status_value,
    }


def _list_accessible(list_obj: List, current_user) -> bool:
    if list_obj.visibility != ListVisibility.PRIVATE:
        return True
    return str(list_obj.owner_guid) == str(current_user.guid)


def _list_item_payload(entry) -> dict[str, Any] | None:
    if not entry.item_data:
        return None
    item = dict(entry.item_data)
    item_guid = item.get("guid") or entry.item_guid
    item["guid"] = str(item_guid)
    item_type = entry.item_type.value if hasattr(entry.item_type, "value") else str(entry.item_type)
    item.setdefault("type", item_type)
    item.setdefault("media_type", _LIST_ITEM_TYPE_TO_MEDIA_TYPE.get(item_type, item_type))
    return item


async def _drop_gated_items(
    db: DatabaseSession,
    items: list[dict[str, Any]],
    current_user,
    permissions,
) -> list[dict[str, Any]]:
    """Drop items the user may not see (parental age + library gate).

    Curated LIST / TRENDING / FAVORITES / HERO rows are resolved purely by GUID
    and would otherwise bypass the age/library gate that the search and latest
    rows enforce. Only items that exist locally *and* violate the gate are
    removed — items absent from the local DB carry no age we can evaluate and
    are left as-is (playback/import stay separately gated). No-op for
    unrestricted (e.g. superuser / full-access adult) accounts.
    """
    if not items:
        return items

    max_age = max_age_for_user(current_user)
    allowed_types = allowed_media_types_for_permissions(current_user, permissions)
    unrestricted_libraries = allowed_types is None or set(allowed_types) >= set(MediaType)
    if max_age is None and unrestricted_libraries:
        return items

    allowed_type_set = None if allowed_types is None else set(allowed_types)
    guids: list[uuid.UUID] = []
    for item in items:
        raw = item.get("guid")
        if raw is None:
            continue
        try:
            guids.append(uuid.UUID(str(raw)))
        except (ValueError, TypeError):
            continue
    if not guids:
        return items

    result = await db.execute(
        select(MediaItem.guid, MediaItem.min_age, MediaItem.media_type).where(
            MediaItem.guid.in_(guids)
        )
    )
    blocked: set[str] = set()
    for guid, min_age, media_type in result.all():
        if allowed_type_set is not None and media_type not in allowed_type_set:
            blocked.add(str(guid))
            continue
        if max_age is not None and min_age is not None and min_age > max_age:
            blocked.add(str(guid))
    if not blocked:
        return items
    return [item for item in items if str(item.get("guid")) not in blocked]


async def _gate_section_payload(
    db: DatabaseSession,
    payload: dict[str, Any],
    current_user,
    permissions,
) -> dict[str, Any]:
    """Apply :func:`_drop_gated_items` to a rendered section's item collections."""
    items = payload.get("rendered_items")
    if items:
        payload["rendered_items"] = await _drop_gated_items(
            db, items, current_user, permissions
        )
    prefix_lists = payload.get("rendered_prefix_lists")
    if prefix_lists:
        for entry in prefix_lists:
            entry_items = (entry or {}).get("items")
            if entry_items:
                entry["items"] = await _drop_gated_items(
                    db, entry_items, current_user, permissions
                )
    return payload


async def _render_list_items(
    service: ListService,
    list_obj: List,
    current_user,
    limit: int,
) -> list[dict[str, Any]]:
    if not _list_accessible(list_obj, current_user):
        return []

    friend_watchers_for_user = None
    if list_obj.update_source and list_obj.update_source.startswith("rec:friends_watching:"):
        friend_watchers_for_user = str(current_user.guid)

    entries, _total = await service.get_items_with_data(
        str(list_obj.guid),
        0,
        limit,
        language=getattr(current_user, "ui_language", None),
        friend_watchers_for_user=friend_watchers_for_user,
    )
    return [item for entry in entries if (item := _list_item_payload(entry))]


async def _render_list_section(
    db: DatabaseSession,
    section: PageSection,
    current_user,
) -> dict[str, Any]:
    service = ListService(db)
    config = section.config or {}
    item_limit = _clamped_limit(config.get("max_items"), 20)
    prefix = config.get("list_update_source_prefix")

    if prefix:
        max_rows = _clamped_limit(config.get("max_rows"), 3, 20)
        lists, _total = await service.get_all(
            skip=0,
            limit=max_rows,
            owner_guid=str(current_user.guid),
            current_user_guid=str(current_user.guid),
            current_user_is_superuser=bool(getattr(current_user, "is_superuser", False)),
            update_source_prefix=prefix,
        )
        summaries = await service.get_lists_with_item_types(lists)
        rendered_lists = []
        for list_obj, summary in zip(lists, summaries, strict=False):
            items = await _render_list_items(service, list_obj, current_user, item_limit)
            if items:
                payload = summary.model_dump(mode="json")
                payload["items"] = items
                rendered_lists.append(payload)
        return {"rendered_prefix_lists": rendered_lists}

    list_obj = None
    list_guid = config.get("list_guid")
    if list_guid:
        list_obj = await service.get_by_id(str(list_guid))
    elif config.get("list_update_source"):
        lists, _total = await service.get_all(
            skip=0,
            limit=1,
            owner_guid=str(current_user.guid),
            current_user_guid=str(current_user.guid),
            current_user_is_superuser=bool(getattr(current_user, "is_superuser", False)),
            update_source=config["list_update_source"],
        )
        list_obj = lists[0] if lists else None

    if not list_obj:
        return {"rendered_items": [], "rendered_list_guid": None}

    return {
        "rendered_items": await _render_list_items(service, list_obj, current_user, item_limit),
        "rendered_list_guid": list_obj.guid,
    }


def _search_payload(filters: dict[str, Any], media_type: str | None, limit: int) -> dict[str, Any]:
    allowed_fields = SearchRequest.model_fields.keys()
    payload = {
        key: value
        for key, value in (filters or {}).items()
        if key in allowed_fields and value not in (None, "")
    }
    if not payload.get("media_type") and media_type:
        payload["media_type"] = media_type
    payload["per_page"] = limit
    payload["page"] = 1
    payload["search_type"] = str(payload.get("media_type") or "all").lower()
    return payload


async def _render_search_items(
    db: DatabaseSession,
    filters: dict[str, Any],
    media_type: str | None,
    current_user,
    permissions,
    limit: int,
) -> list[dict[str, Any]]:
    request = SearchRequest(**_search_payload(filters, media_type, limit))
    result = await search_local_content(db, request, current_user, permissions)
    return list(result.get("hits") or [])[:limit]


async def _render_latest_items(
    db: DatabaseSession,
    current_user,
    permissions,
    media_type: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    media_type_filter = _media_type_enum(media_type)
    result = await db.execute(
        select(MediaItem)
        .options(selectinload(MediaItem.genres), selectinload(MediaItem.platforms))
        .where(
            *visibility_conditions(current_user, permissions, media_type_filter),
            MediaItem.parent_guid.is_(None),
        )
        .order_by(desc(MediaItem.created_at), desc(MediaItem.release_date).nulls_last())
        .limit(limit)
    )
    summaries = await _summaries(
        db,
        list(result.scalars().unique().all()),
        getattr(current_user, "ui_language", None),
    )
    return [summary.model_dump(mode="json") for summary in summaries]


async def _render_trailer_items(
    db: DatabaseSession,
    section: PageSection,
    media_type: str | None,
    current_user,
    permissions,
) -> list[dict[str, Any]]:
    config = section.config or {}
    response = await browse_trailers(
        db,
        current_user,
        permissions,
        media_type=_media_type_enum(config.get("media_type") or media_type),
        search_term=(config.get("search_term") or None),
        skip=0,
        limit=_clamped_limit(config.get("max_items"), 20),
    )
    return [item.model_dump(mode="json") for item in response.items]


async def _render_favorite_items(
    db: DatabaseSession,
    section: PageSection,
    media_type: str | None,
    current_user,
) -> list[dict[str, Any]]:
    config = section.config or {}
    limit = _clamped_limit(config.get("max_items"), 20)
    response = await FavoriteService(db).list_favorites(
        current_user.guid,
        None,
        ui_language=getattr(current_user, "ui_language", None),
    )
    target_media_type = (config.get("media_type") or media_type or "").upper()
    items = []
    for favorite in response.items:
        item = favorite.model_dump(mode="json")
        item["guid"] = item.get("media_item_guid") or item.get("guid")
        item["poster_path"] = item.get("poster_path") or item.get("poster_url")
        if target_media_type and item.get("media_type") != target_media_type:
            continue
        items.append(item)
        if len(items) >= limit:
            break
    return items


async def _render_trending_items(
    db: DatabaseSession,
    media_type: str | None,
    current_user,
) -> list[dict[str, Any]]:
    sources = ["trending_movies", "trending_shows", "trending_games", "trending_music"]
    if media_type:
        source_by_type = {
            "MOVIES": "trending_movies",
            "SHOWS": "trending_shows",
            "GAMES": "trending_games",
            "MUSIC": "trending_music",
        }
        sources = [source_by_type[media_type.upper()]] if media_type.upper() in source_by_type else []

    service = ListService(db)
    items: list[dict[str, Any]] = []
    for source in sources:
        lists, _total = await service.get_all(
            skip=0,
            limit=1,
            owner_guid=None,
            current_user_guid=str(current_user.guid),
            current_user_is_superuser=bool(getattr(current_user, "is_superuser", False)),
            update_source=source,
        )
        if not lists:
            continue
        items.extend(await _render_list_items(service, lists[0], current_user, 10))
    return items[:20]


async def _render_section(
    db: DatabaseSession,
    section: PageSection,
    media_type: str | None,
    current_user,
    permissions,
) -> dict[str, Any]:
    section_type = _section_type_value(section)
    config = section.config or {}
    limit = _clamped_limit(config.get("max_items"), 20)

    if section_type == SectionType.LATEST_ITEMS.value:
        return {
            "rendered_items": await _render_latest_items(
                db,
                current_user,
                permissions,
                config.get("media_type") or media_type,
                limit,
            )
        }
    if section_type == SectionType.DYNAMIC_SEARCH.value:
        return {
            "rendered_items": await _render_search_items(
                db,
                config.get("filters") or {},
                media_type,
                current_user,
                permissions,
                limit,
            )
        }
    if section_type == SectionType.GENRE.value:
        filters = dict(config.get("filters") or {})
        if config.get("genre_id"):
            filters["genre_id"] = config["genre_id"]
        return {
            "rendered_items": await _render_search_items(
                db,
                filters,
                media_type,
                current_user,
                permissions,
                limit,
            )
        }
    if section_type == SectionType.LIST.value:
        return await _gate_section_payload(
            db,
            await _render_list_section(db, section, current_user),
            current_user,
            permissions,
        )
    if section_type == SectionType.HERO_CAROUSEL.value:
        source_type = config.get("source_type")
        if source_type == "list" or config.get("list_guid") or config.get("list_update_source"):
            return await _gate_section_payload(
                db,
                await _render_list_section(db, section, current_user),
                current_user,
                permissions,
            )
        if source_type == "dynamic_search":
            return {
                "rendered_items": await _render_search_items(
                    db,
                    config.get("filters") or {},
                    media_type,
                    current_user,
                    permissions,
                    limit,
                )
            }
        return await _gate_section_payload(
            db,
            {"rendered_items": await _render_trending_items(db, media_type, current_user)},
            current_user,
            permissions,
        )
    if section_type == SectionType.FAVORITES.value:
        return await _gate_section_payload(
            db,
            {"rendered_items": await _render_favorite_items(db, section, media_type, current_user)},
            current_user,
            permissions,
        )
    if section_type == SectionType.TRAILERS.value:
        return {
            "rendered_items": await _render_trailer_items(
                db,
                section,
                media_type,
                current_user,
                permissions,
            )
        }
    return {}


# Section types whose content is fetched server-side. If one of these
# renders empty for the current user, we drop it from the rendered
# payload so the client doesn't have to flicker through a "loading"
# state on a section that will end up hidden anyway.
_PRERENDERED_SECTION_TYPES: frozenset[str] = frozenset({
    SectionType.LATEST_ITEMS.value,
    SectionType.DYNAMIC_SEARCH.value,
    SectionType.GENRE.value,
    SectionType.LIST.value,
    SectionType.HERO_CAROUSEL.value,
    SectionType.FAVORITES.value,
    SectionType.TRAILERS.value,
})


def _section_has_content(section_payload: dict[str, Any]) -> bool:
    """True iff the rendered payload carries at least one item.

    Client-rendered section types are treated as "has content" here —
    the client-side pre-check in ``_client_section_will_be_empty`` is
    what actually drops them when applicable.
    """
    section_type = section_payload.get("section_type")
    if section_type not in _PRERENDERED_SECTION_TYPES:
        return True
    if section_payload.get("rendered_items"):
        return True
    prefix_lists = section_payload.get("rendered_prefix_lists") or []
    if any((entry or {}).get("items") for entry in prefix_lists):
        return True
    # A LIST section that resolved to a real (but empty) list still
    # carries useful UX (named heading, "no items yet" placeholder).
    if section_payload.get("rendered_list_guid"):
        return True
    return False


async def _client_section_will_be_empty(
    db: AsyncSession,
    section: PageSection,
    media_type: str | None,
    current_user,
) -> bool:
    """Best-effort pre-flight check for client-rendered section types.

    Returns True when we can be confident the client component will
    end up with zero items and silently hide itself. Used to avoid the
    UX flicker of empty sections appearing and disappearing on first
    paint. False = unsure → let the client decide.
    """
    section_type = _section_type_value(section)
    if section_type == SectionType.CONTINUE_WATCHING.value:
        from pyrate.models.viewing_history import ViewingHistory
        from pyrate.models.media import MediaItem

        stmt = (
            select(ViewingHistory.guid)
            .join(MediaItem, MediaItem.guid == ViewingHistory.media_item_guid)
            .where(ViewingHistory.user_guid == current_user.guid)
            .where(ViewingHistory.is_completed.is_(False))
            .where(ViewingHistory.progress_seconds > 0)
        )
        if media_type:
            wanted = {media_type.upper()}
            # Episodes count as SHOWS for the purpose of the row.
            if "SHOWS" in wanted:
                wanted.add("EPISODES")
            stmt = stmt.where(MediaItem.media_type.in_(wanted))
        stmt = stmt.limit(1)
        row = (await db.execute(stmt)).first()
        return row is None
    # Unknown section types: don't second-guess them.
    return False


async def _render_layout_payload(
    db: DatabaseSession,
    layout: PageLayout,
    media_type: str | None,
    current_user,
    permissions,
    *,
    drop_empty: bool = True,
) -> dict[str, Any]:
    payload = PageLayoutRead.model_validate(layout).model_dump(mode="json")
    rendered_sections = []
    dropped = 0
    for section in sorted(layout.sections or [], key=lambda item: item.order_index):
        section_payload = PageSectionRead.model_validate(section).model_dump(mode="json")
        section_payload["rendered_items"] = []
        section_payload["rendered_prefix_lists"] = []
        section_payload["rendered_list_guid"] = None
        if section.is_enabled:
            try:
                section_payload.update(
                    await _render_section(
                        db,
                        section,
                        media_type,
                        current_user,
                        permissions,
                    )
                )
            except Exception as exc:
                logger.warning(
                    "Failed to render page section %s (%s): %s",
                    section.guid,
                    _section_type_value(section),
                    exc,
                )
        if drop_empty and section.is_enabled:
            section_type = section_payload.get("section_type")
            is_prerendered = section_type in _PRERENDERED_SECTION_TYPES
            if is_prerendered and not _section_has_content(section_payload):
                dropped += 1
                continue
            if not is_prerendered and await _client_section_will_be_empty(
                db, section, media_type, current_user
            ):
                dropped += 1
                continue
        rendered_sections.append(section_payload)

    payload["sections"] = rendered_sections
    payload["cache_status"] = "fresh"
    if dropped:
        payload["empty_sections_dropped"] = dropped
    return PageLayoutRenderedRead.model_validate(payload).model_dump(mode="json")


def _tmdb_variant_url(path: str, size: str) -> str:
    normalized = path if path.startswith("/") else f"/{path}"
    return f"{_TMDB_IMAGE_BASE}/{size}{normalized}"


def _artwork_url(value: Any, *, is_backdrop: bool = False) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    if value.startswith("http://") or value.startswith("https://"):
        return value
    if value.startswith("/"):
        return _tmdb_variant_url(value, "w1280" if is_backdrop else "w500")
    return None


def _collect_artwork_urls_from_item(item: dict[str, Any], urls: list[str]) -> None:
    for key in ("poster_path", "poster_url", "cover_url"):
        if url := _artwork_url(item.get(key)):
            urls.append(url)
    if url := _artwork_url(item.get("backdrop_path"), is_backdrop=True):
        urls.append(url)
    if isinstance(item.get("media_item"), dict):
        _collect_artwork_urls_from_item(item["media_item"], urls)


def _collect_artwork_urls(payload: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for section in payload.get("sections") or []:
        for item in section.get("rendered_items") or []:
            if isinstance(item, dict):
                _collect_artwork_urls_from_item(item, urls)
        for rendered_list in section.get("rendered_prefix_lists") or []:
            for item in rendered_list.get("items") or []:
                if isinstance(item, dict):
                    _collect_artwork_urls_from_item(item, urls)

    seen: set[str] = set()
    return [url for url in urls if not (url in seen or seen.add(url))]


async def _warm_rendered_artwork(urls: list[str]) -> None:
    from pyrate.api.v1.media import warm_artwork_cache_urls

    await warm_artwork_cache_urls(urls, limit=50)


async def _render_layout_response(
    db: DatabaseSession,
    request: Request,
    background_tasks: BackgroundTasks,
    layout: PageLayout | None,
    scope: str,
    media_type: str | None,
    current_user,
    permissions,
    *,
    drop_empty: bool = True,
) -> Response:
    if not layout:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Layout not found")

    # ``drop_empty`` feeds the cache key so the drop=true and drop=false
    # responses don't share storage.
    scope_with_flag = f"{scope}|drop_empty={int(bool(drop_empty))}"
    key = _layout_cache_key(layout, scope_with_flag, current_user, permissions)
    if_none_match = request.headers.get("if-none-match")
    cached = await _read_render_cache(RENDER_CACHE_PREFIX, key)
    if cached:
        record_layout_cache_event("hit")
        etag = cached.get("etag") or _payload_etag(cached["payload"])
        headers = _render_headers(etag, "hit")
        if if_none_match == etag:
            record_layout_cache_event("not_modified")
            return Response(status_code=304, headers=headers)
        return JSONResponse(content=cached["payload"], headers=headers)

    try:
        with observe_layout_render(scope, "miss"):
            payload = await _render_layout_payload(
                db,
                layout,
                media_type,
                current_user,
                permissions,
                drop_empty=drop_empty,
            )
        etag = _payload_etag(payload)
        await _write_render_cache(key, payload, etag)
        record_layout_cache_event("miss")
        urls = _collect_artwork_urls(payload)
        if urls:
            background_tasks.add_task(_warm_rendered_artwork, urls)
        headers = _render_headers(etag, "miss")
        if if_none_match == etag:
            return Response(status_code=304, headers=headers)
        return JSONResponse(content=payload, headers=headers)
    except Exception:
        logger.exception("Failed to render page layout %s", layout.guid)
        stale = await _read_render_cache(RENDER_STALE_PREFIX, key)
        if stale:
            record_layout_cache_event("stale")
            etag = stale.get("etag") or _payload_etag(stale["payload"])
            payload = dict(stale["payload"])
            payload["cache_status"] = "stale"
            return JSONResponse(
                content=payload,
                headers=_render_headers(etag, "stale"),
            )
        raise


# ---------------------------------------------------------------------------
# Public endpoints (authenticated users)
# ---------------------------------------------------------------------------


_LAYOUT_CACHE_CONTROL = "private, max-age=300"


@router.get("/slug/{slug}", response_model=PageLayoutRead)
async def get_layout_by_slug(
    db: DatabaseSession,
    current_user: CurrentUser,
    response: Response,
    slug: str,
):
    """Get an active page layout by slug (e.g. 'home')."""
    service = PageLayoutService(db)
    layout = await service.get_layout_by_slug(slug)
    if not layout:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Layout not found")
    response.headers["Cache-Control"] = _LAYOUT_CACHE_CONTROL
    return layout


@router.get("/slug/{slug}/rendered", response_model=PageLayoutRenderedRead)
async def get_rendered_layout_by_slug(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    request: Request,
    background_tasks: BackgroundTasks,
    slug: str,
    include_empty: bool = False,
):
    """Get an active layout with section contents pre-rendered for fast first paint.

    Defaults to skipping sections that produced no content for this user.
    Pass ``?include_empty=true`` (e.g. from admin tooling) to keep them.
    """
    service = PageLayoutService(db)
    layout = await service.get_layout_by_slug(slug)
    return await _render_layout_response(
        db,
        request,
        background_tasks,
        layout,
        f"slug:{slug}",
        None,
        current_user,
        permissions,
        drop_empty=not include_empty,
    )


@router.get("/library/{library_guid}", response_model=PageLayoutRead)
async def get_layout_for_library(
    db: DatabaseSession,
    current_user: CurrentUser,
    response: Response,
    library_guid: uuid.UUID,
):
    """Get page layout for a library, falling back to default 'home' layout."""
    service = PageLayoutService(db)
    layout = await service.get_layout_for_library(library_guid)
    if not layout:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Layout not found")
    response.headers["Cache-Control"] = _LAYOUT_CACHE_CONTROL
    return layout


@router.get("/library/{library_guid}/rendered", response_model=PageLayoutRenderedRead)
async def get_rendered_layout_for_library(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    request: Request,
    background_tasks: BackgroundTasks,
    library_guid: uuid.UUID,
    include_empty: bool = False,
):
    """Get a library layout with section contents pre-rendered.

    Empty sections are dropped by default; pass ``?include_empty=true``
    to surface them.
    """
    service = PageLayoutService(db)
    layout = await service.get_layout_for_library(library_guid)
    return await _render_layout_response(
        db,
        request,
        background_tasks,
        layout,
        f"library:{library_guid}",
        None,
        current_user,
        permissions,
        drop_empty=not include_empty,
    )


@router.get("/media-type/{media_type}", response_model=PageLayoutRead)
async def get_layout_for_media_type(
    db: DatabaseSession,
    current_user: CurrentUser,
    response: Response,
    media_type: str,
):
    """Get page layout for a media type (e.g. 'movies', 'shows'), falling back to 'home' layout."""
    service = PageLayoutService(db)
    layout = await service.get_layout_for_media_type(media_type.upper())
    if not layout:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Layout not found")
    response.headers["Cache-Control"] = _LAYOUT_CACHE_CONTROL
    return layout


@router.get("/media-type/{media_type}/rendered", response_model=PageLayoutRenderedRead)
async def get_rendered_layout_for_media_type(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    request: Request,
    background_tasks: BackgroundTasks,
    media_type: str,
    include_empty: bool = False,
):
    """Get a media-type layout with section contents pre-rendered.

    Empty sections are dropped by default; pass ``?include_empty=true``
    to surface them.
    """
    service = PageLayoutService(db)
    normalized_media_type = media_type.upper()
    layout = await service.get_layout_for_media_type(normalized_media_type)
    return await _render_layout_response(
        db,
        request,
        background_tasks,
        layout,
        f"media-type:{normalized_media_type}",
        normalized_media_type,
        current_user,
        permissions,
        drop_empty=not include_empty,
    )


# ---------------------------------------------------------------------------
# Admin endpoints (superuser only)
# ---------------------------------------------------------------------------


@router.get("", response_model=list[PageLayoutSummary])
async def list_layouts(
    db: DatabaseSession,
    current_user: CurrentSuperuser,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    """List all page layouts (admin only)."""
    service = PageLayoutService(db)
    layouts, _total = await service.get_all_layouts(skip=skip, limit=limit)
    return [
        PageLayoutSummary(
            guid=layout.guid,
            name=layout.name,
            slug=layout.slug,
            library_guid=layout.library_guid,
            is_active=layout.is_active,
            section_count=len(layout.sections),
            created_at=layout.created_at,
            updated_at=layout.updated_at,
        )
        for layout in layouts
    ]


@router.post("", response_model=PageLayoutRead, status_code=status.HTTP_201_CREATED)
async def create_layout(
    db: DatabaseSession,
    current_user: CurrentSuperuser,
    data: PageLayoutCreate,
):
    """Create a new page layout (admin only)."""
    service = PageLayoutService(db)
    sections = [s.model_dump() for s in data.sections] if data.sections else None
    try:
        layout = await service.create_layout(
            name=data.name,
            slug=data.slug,
            library_guid=data.library_guid,
            is_active=data.is_active,
            sections=sections,
        )
    except ValueError as exc:
        msg = str(exc)
        if msg.startswith("slug_taken:"):
            existing_guid = msg.split(":", 1)[1]
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "slug_taken",
                    "message": f"A layout with slug '{data.slug}' already exists.",
                    "existing_layout_guid": existing_guid,
                },
            ) from exc
        raise
    logger.info("Admin %s created page layout %s", current_user.guid, layout.guid)
    await clear_rendered_layout_cache("page_layout_changed")
    return layout


@router.get("/{layout_guid}", response_model=PageLayoutRead)
async def get_layout(
    db: DatabaseSession,
    current_user: CurrentSuperuser,
    layout_guid: uuid.UUID,
):
    """Get a specific page layout by GUID (admin only)."""
    service = PageLayoutService(db)
    layout = await service.get_layout_by_guid(layout_guid)
    if not layout:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Layout not found")
    return layout


@router.put("/{layout_guid}", response_model=PageLayoutRead)
async def update_layout(
    db: DatabaseSession,
    current_user: CurrentSuperuser,
    layout_guid: uuid.UUID,
    data: PageLayoutUpdate,
):
    """Update a page layout (admin only)."""
    service = PageLayoutService(db)
    layout = await service.update_layout(
        layout_guid,
        name=data.name,
        slug=data.slug,
        library_guid=data.library_guid,
        is_active=data.is_active,
    )
    if not layout:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Layout not found")
    logger.info("Admin %s updated page layout %s", current_user.guid, layout_guid)
    await clear_rendered_layout_cache("page_layout_changed")
    return layout


@router.delete("/{layout_guid}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_layout(
    db: DatabaseSession,
    current_user: CurrentSuperuser,
    layout_guid: uuid.UUID,
):
    """Delete a page layout (admin only)."""
    service = PageLayoutService(db)
    deleted = await service.delete_layout(layout_guid)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Layout not found")
    logger.info("Admin %s deleted page layout %s", current_user.guid, layout_guid)
    await clear_rendered_layout_cache("page_layout_changed")


# ---------------------------------------------------------------------------
# Section management (admin only)
# ---------------------------------------------------------------------------


@router.post(
    "/{layout_guid}/sections",
    response_model=PageSectionRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_section(
    db: DatabaseSession,
    current_user: CurrentSuperuser,
    layout_guid: uuid.UUID,
    data: PageSectionCreate,
):
    """Add a section to a page layout (admin only)."""
    service = PageLayoutService(db)
    # Verify layout exists
    layout = await service.get_layout_by_guid(layout_guid)
    if not layout:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Layout not found")

    section = await service.add_section(
        layout_guid=layout_guid,
        section_type=data.section_type,
        order_index=data.order_index,
        title=data.title,
        config=data.config,
        is_enabled=data.is_enabled,
    )
    logger.info("Admin %s added section %s to layout %s", current_user.guid, section.guid, layout_guid)
    await clear_rendered_layout_cache("page_layout_changed")
    return section


@router.put("/{layout_guid}/sections/{section_guid}", response_model=PageSectionRead)
async def update_section(
    db: DatabaseSession,
    current_user: CurrentSuperuser,
    layout_guid: uuid.UUID,
    section_guid: uuid.UUID,
    data: PageSectionUpdate,
):
    """Update a section in a page layout (admin only)."""
    service = PageLayoutService(db)
    section = await service.get_section_by_guid(section_guid)
    if not section or section.layout_guid != layout_guid:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Section not found")

    updated = await service.update_section(
        section_guid,
        section_type=data.section_type,
        order_index=data.order_index,
        title=data.title,
        config=data.config,
        is_enabled=data.is_enabled,
    )
    logger.info("Admin %s updated section %s in layout %s", current_user.guid, section_guid, layout_guid)
    await clear_rendered_layout_cache("page_layout_changed")
    return updated


@router.delete(
    "/{layout_guid}/sections/{section_guid}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_section(
    db: DatabaseSession,
    current_user: CurrentSuperuser,
    layout_guid: uuid.UUID,
    section_guid: uuid.UUID,
):
    """Remove a section from a page layout (admin only)."""
    service = PageLayoutService(db)
    section = await service.get_section_by_guid(section_guid)
    if not section or section.layout_guid != layout_guid:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Section not found")

    await service.delete_section(section_guid)
    logger.info("Admin %s deleted section %s from layout %s", current_user.guid, section_guid, layout_guid)
    await clear_rendered_layout_cache("page_layout_changed")


@router.put("/{layout_guid}/sections-order", response_model=PageLayoutRead)
async def reorder_sections(
    db: DatabaseSession,
    current_user: CurrentSuperuser,
    layout_guid: uuid.UUID,
    data: ReorderSectionsRequest,
):
    """Reorder sections within a page layout (admin only)."""
    service = PageLayoutService(db)
    layout = await service.reorder_sections(layout_guid, data.section_order)
    if not layout:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Layout not found")
    await clear_rendered_layout_cache("page_layout_changed")
    return layout
