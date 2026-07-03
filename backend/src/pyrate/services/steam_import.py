"""Import a parsed Steam library into pyrate :class:`MediaItem` games.

Turns a list of ``{"app_id", "name", "installed"}`` dicts into GAMES media
items, deduplicated by a ``steam`` :class:`MediaExternalId`. Each item is
stamped with ``extra_data.lightrays = {"profile": "steam", "app_ref": app_id}``
so the launch resolver (``services/container_profiles.resolve_launch_config``)
auto-launches that exact Steam app.
"""

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.models.media import MediaExternalId, MediaItem, MediaType
from pyrate.services.media import MediaService
from pyrate.utils.http import (
    host_key,
    make_async_client,
    request_with_resilience,
)

logger = logging.getLogger(__name__)

STEAM_PROVIDER = "steam"

# Keyless public store endpoint — no API key required. ``filters=basic`` keeps
# the payload tiny (we only want the name).
_STEAM_APPDETAILS_URL = "https://store.steampowered.com/api/appdetails"


async def import_steam_games(
    db: AsyncSession,
    games: list[dict],
    *,
    enrich: bool = True,
) -> dict:
    """Upsert a parsed Steam game list into GAMES media items.

    Each game is ``{"app_id": str, "name": str | None, "installed": bool}``.

    For every game a :class:`MediaItem` (``media_type == GAMES``) is upserted,
    deduplicated by a ``steam`` :class:`MediaExternalId` on ``app_id``:

    - existing item with that steam id -> update (title if a name is known,
      and merge the lightrays launch block);
    - otherwise -> create the item and its steam external id.

    ``extra_data.lightrays`` is merged (never clobbered) so an existing IGDB
    blob or per-game overrides survive; only ``profile``/``app_ref`` are set.

    When a name is missing and ``enrich`` is true, the name is best-effort
    fetched from the keyless Steam store endpoint; on any failure it falls back
    to ``f"Steam App {app_id}"`` (for creates) or leaves an existing title
    untouched (for updates).

    Returns ``{"created", "updated", "skipped", "items"}`` where ``items`` are
    the guids (as strings) of every item created or updated.
    """
    media_service = MediaService(db)
    created = 0
    updated = 0
    skipped = 0
    items: list[str] = []

    for game in games:
        app_id = str(game.get("app_id") or "").strip()
        if not app_id:
            skipped += 1
            continue

        name = game.get("name")

        existing = await _find_by_steam_id(db, app_id)

        # Resolve a display name: prefer the supplied name, else best-effort
        # enrich from Steam. May stay None (handled per create/update below).
        resolved_name = name
        if not resolved_name and enrich:
            resolved_name = await _fetch_steam_name(app_id)

        if existing is not None:
            if resolved_name:
                existing.title = resolved_name
            _merge_lightrays(existing, app_id)
            updated += 1
            items.append(str(existing.guid))
            continue

        title = resolved_name or f"Steam App {app_id}"
        item = await media_service.create_media_item(
            media_type=MediaType.GAMES,
            title=title,
            commit=False,
        )
        _merge_lightrays(item, app_id)
        await media_service.add_external_id(
            media_item_guid=item.guid,
            provider=STEAM_PROVIDER,
            external_id=app_id,
            commit=False,
        )
        created += 1
        items.append(str(item.guid))

    await db.commit()
    logger.info(
        "Steam import: created=%d updated=%d skipped=%d", created, updated, skipped
    )
    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "items": items,
    }


async def _find_by_steam_id(db: AsyncSession, app_id: str) -> MediaItem | None:
    """Return the GAMES item carrying this steam external id, if any."""
    result = await db.execute(
        select(MediaItem)
        .join(MediaExternalId)
        .where(MediaExternalId.provider == STEAM_PROVIDER)
        .where(MediaExternalId.external_id == app_id)
        .where(MediaItem.media_type == MediaType.GAMES)
        .limit(1)
    )
    return result.scalar_one_or_none()


def _merge_lightrays(item: MediaItem, app_id: str) -> None:
    """Merge the lightrays launch block into ``item.extra_data`` in place.

    Preserves every other ``extra_data`` key (e.g. an IGDB blob) and every
    other ``lightrays`` key (e.g. a per-game ``docker_image``); only sets
    ``profile``/``app_ref``. A fresh dict is assigned so SQLAlchemy tracks the
    change without needing a mutable-JSON wrapper.
    """
    raw = item.extra_data
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = None
    existing = dict(raw) if isinstance(raw, dict) else {}

    lr_raw = existing.get("lightrays")
    lightrays = dict(lr_raw) if isinstance(lr_raw, dict) else {}
    lightrays["profile"] = STEAM_PROVIDER
    lightrays["app_ref"] = app_id
    existing["lightrays"] = lightrays

    item.extra_data = existing


async def _fetch_steam_name(app_id: str) -> str | None:
    """Best-effort name lookup from the keyless Steam store endpoint.

    Returns the app name, or ``None`` on any error (network, non-200, missing
    payload) so the caller can fall back to a synthetic title. Network access
    is confined to this helper so callers can disable it (``enrich=False``) or
    mock it in tests.
    """
    try:
        async with make_async_client() as client:
            resp = await request_with_resilience(
                lambda: client.get(
                    _STEAM_APPDETAILS_URL,
                    params={"appids": app_id, "filters": "basic"},
                ),
                breaker_key=host_key(_STEAM_APPDETAILS_URL),
            )
        resp.raise_for_status()
        payload = resp.json()
        entry = payload.get(str(app_id)) or {}
        data = entry.get("data")
        if entry.get("success") and isinstance(data, dict):
            steam_name = data.get("name")
            if steam_name:
                return str(steam_name)
    except Exception as exc:  # noqa: BLE001 — best-effort enrichment
        logger.warning("Steam appdetails fetch failed for app %s: %s", app_id, exc)
    return None
