"""Unified availability check for all media types."""

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from streamarr.models.media import (
    MediaFile,
    MediaItem,
    MediaRelease,
    MediaReleaseLink,
)
from streamarr.models.media_watch import MediaWatch
from streamarr.services.download_status import download_phase

logger = logging.getLogger(__name__)


@dataclass
class AvailabilityResult:
    """Result of an availability check."""

    status: str  # "available", "downloading", "searching", "unavailable"
    target_guid: uuid.UUID | None = None
    target_action: str | None = None  # "resume", "next", "start", "replay"
    progress_seconds: int = 0
    download_progress: float | None = None
    download_status: str | None = None
    download_phase: str | None = None
    download_status_detail: str | None = None
    is_watched: bool = False


async def check_availability(
    db: AsyncSession,
    media_item: MediaItem,
    user_guid: uuid.UUID,
) -> AvailabilityResult:
    """Check availability for any media type.

    - Movies/Episodes/Songs: check files → downloads → releases → trigger search
    - Shows: find next unplayed episode across all seasons, check its availability
    - Seasons: find next unplayed episode in this season, check its availability
    - Games: always available (Lightrays streaming)
    - Artists/Albums: check if any child has files
    """
    media_type = media_item.media_type.value
    logger.info("Checking availability for %s (%s, type=%s, parent=%s)",
                media_item.title, media_item.guid, media_type, media_item.parent_guid)

    # Games: a streaming game (Steam, admin-configured Wine runtime — any
    # explicit non-retro profile) launches via Lightrays with no local file and
    # is always available. A retro/ROM game is file-based like a movie:
    # available only once its ROM is downloaded, downloading/downloadable while
    # it isn't — so it flows through the SAME acquisition path as other media.
    if media_type == "GAMES":
        raw = media_item.extra_data
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                raw = None
        lr = raw.get("lightrays") if isinstance(raw, dict) else None
        explicit_profile = lr.get("profile") if isinstance(lr, dict) else None
        if explicit_profile and explicit_profile != "retro":
            return AvailabilityResult(status="available", target_guid=media_item.guid)
        return await _check_leaf_availability(db, media_item, user_guid)

    # Shows (top-level, no parent) — find next unplayed episode
    if media_type == "SHOWS" and media_item.parent_guid is None:
        return await _check_show_availability(db, media_item, user_guid)

    # Seasons (SHOWS with parent, has children) — find next unplayed episode in this season
    if media_type == "SHOWS" and media_item.parent_guid is not None:
        # Check if this is a season (has children) vs episode (no children)
        children = await _get_children(db, media_item.guid)
        if children:
            return await _check_season_availability(db, media_item, children, user_guid)
        # Fall through to leaf item check (episode)

    # Artists/Albums — check if any child track has files
    if media_type in ("ARTISTS", "ALBUMS"):
        return await _check_collection_availability(db, media_item, user_guid)

    # Leaf items: Movies, Episodes, Songs, Music
    return await _check_leaf_availability(db, media_item, user_guid)


async def _check_leaf_availability(
    db: AsyncSession,
    media_item: MediaItem,
    user_guid: uuid.UUID,
) -> AvailabilityResult:
    """Check availability for a single playable item (movie, episode, song)."""
    from streamarr.models.downloads import Download, DownloadStatus

    item_guid = media_item.guid

    # 1. Check if file exists on disk
    file_result = await db.execute(
        select(MediaFile).where(MediaFile.media_item_guid == item_guid)
    )
    file = file_result.scalars().first()
    # Path.exists() is a blocking stat() — run it off the event loop so slow /
    # remote storage doesn't stall every other coroutine.
    if file and await asyncio.to_thread(Path(file.file_path).exists):
        return AvailabilityResult(status="available", target_guid=item_guid)

    # 2. Check if download in progress
    download_result = await db.execute(
        select(Download)
        .join(MediaReleaseLink, Download.media_release_link_guid == MediaReleaseLink.guid)
        .join(MediaRelease, MediaReleaseLink.media_release_guid == MediaRelease.guid)
        .where(MediaRelease.media_item_guid == item_guid)
        .where(Download.status.notin_(DownloadStatus.TERMINAL))
    )
    download = download_result.scalars().first()
    if download:
        return AvailabilityResult(
            status="downloading",
            target_guid=item_guid,
            download_progress=download.progress or 0.0,
            download_status=download.status,
            download_phase=download_phase(download.status),
            download_status_detail=download.error_reason,
        )

    # 3. Check for releases with download links
    releases_result = await db.execute(
        select(MediaRelease)
        .where(MediaRelease.media_item_guid == item_guid)
        .options(selectinload(MediaRelease.links))
    )
    releases = releases_result.scalars().all()
    has_releases_with_links = any(r.links for r in releases)

    if has_releases_with_links:
        # Releases exist with download links — can be downloaded
        return AvailabilityResult(
            status="downloading",
            target_guid=item_guid,
            download_progress=0.0,
            download_status="preparing",
            download_phase="preparing",
        )

    # 4. Trigger auto-search if needed (24h cooldown)
    searched = await _maybe_trigger_search(db, media_item, user_guid)

    if releases or searched:
        return AvailabilityResult(
            status="searching",
            target_guid=item_guid,
            download_status="searching",
            download_phase="searching",
            is_watched=await _is_watched(db, item_guid, user_guid),
        )

    # 5. Nothing found
    return AvailabilityResult(
        status="unavailable",
        target_guid=item_guid,
        is_watched=await _is_watched(db, item_guid, user_guid),
    )


async def _check_show_availability(
    db: AsyncSession,
    show: MediaItem,
    user_guid: uuid.UUID,
) -> AvailabilityResult:
    """Check availability for a show — finds next unplayed episode across all seasons."""
    from streamarr.services.library import LibraryService

    service = LibraryService(db)
    seasons = await service.get_children(show.guid, order_by_sequence=True)
    if not seasons:
        return AvailabilityResult(
            status="unavailable",
            is_watched=await _is_watched(db, show.guid, user_guid),
        )

    # Load every episode across all seasons in ONE query (was N+1: one
    # get_children per season), then group by season for ordering.
    season_seq = {s.guid: (s.sequence_number or 0) for s in seasons}
    episode_rows = await db.execute(
        select(MediaItem)
        .where(MediaItem.parent_guid.in_(season_seq.keys()))
        .order_by(MediaItem.sequence_number)
    )
    all_episodes: list[tuple[int, int, MediaItem]] = [
        (season_seq.get(ep.parent_guid, 0), ep.sequence_number or 0, ep)
        for ep in episode_rows.scalars().all()
    ]

    if not all_episodes:
        return AvailabilityResult(
            status="unavailable",
            is_watched=await _is_watched(db, show.guid, user_guid),
        )

    all_episodes.sort(key=lambda x: (x[0], x[1]))
    episodes_only = [ep for _, _, ep in all_episodes]

    target, action, progress = await _find_next_episode(db, episodes_only, user_guid)
    if not target:
        return AvailabilityResult(
            status="unavailable",
            is_watched=await _is_watched(db, show.guid, user_guid),
        )

    # Check the target episode's availability
    leaf_result = await _check_leaf_availability(db, target, user_guid)
    leaf_result.target_action = action
    leaf_result.progress_seconds = progress
    return leaf_result


async def _check_season_availability(
    db: AsyncSession,
    season: MediaItem,
    episodes: list[MediaItem],
    user_guid: uuid.UUID,
) -> AvailabilityResult:
    """Check availability for a season — finds next unplayed episode in this season."""
    # Sort by sequence number
    episodes.sort(key=lambda ep: ep.sequence_number or 0)

    target, action, progress = await _find_next_episode(db, episodes, user_guid)
    if not target:
        return AvailabilityResult(
            status="unavailable",
            is_watched=await _is_watched(db, season.guid, user_guid),
        )

    leaf_result = await _check_leaf_availability(db, target, user_guid)
    leaf_result.target_action = action
    leaf_result.progress_seconds = progress
    return leaf_result


async def _check_collection_availability(
    db: AsyncSession,
    item: MediaItem,
    _user_guid: uuid.UUID,
) -> AvailabilityResult:
    """Check availability for artists/albums.

    - Any child with files → available
    - Any child with releases (e.g. Spotify links) → downloadable
    - Otherwise → unavailable
    """
    children = await _get_children(db, item.guid)
    if not children:
        return AvailabilityResult(status="unavailable")

    # Resolve the leaf items (tracks) in ONE query instead of a get_children per
    # child: for an artist the leaves are the albums' tracks, for an album the
    # leaves are the album's own tracks. A child with no children IS a leaf.
    child_guids = [c.guid for c in children]
    grandchildren = list(
        (
            await db.execute(
                select(MediaItem).where(MediaItem.parent_guid.in_(child_guids))
            )
        ).scalars().all()
    )
    parents_with_children = {gc.parent_guid for gc in grandchildren}
    leaf_guids = [gc.guid for gc in grandchildren]
    leaf_guids += [c.guid for c in children if c.guid not in parents_with_children]
    if not leaf_guids:
        return AvailabilityResult(status="unavailable")

    # Two batched existence checks over all leaves (was O(albums×tracks) N+1).
    has_file = (
        await db.execute(
            select(MediaFile.media_item_guid)
            .where(MediaFile.media_item_guid.in_(leaf_guids))
            .limit(1)
        )
    ).scalars().first()
    if has_file:
        return AvailabilityResult(status="available", target_guid=item.guid)

    has_releases = (
        await db.execute(
            select(MediaRelease.media_item_guid)
            .where(MediaRelease.media_item_guid.in_(leaf_guids))
            .where(MediaRelease.blacklisted_reason.is_(None))
            .limit(1)
        )
    ).scalars().first()
    if has_releases:
        return AvailabilityResult(status="downloadable", target_guid=item.guid)

    return AvailabilityResult(status="unavailable")


async def _find_next_episode(
    db: AsyncSession,
    episodes: list[MediaItem],
    user_guid: uuid.UUID,
) -> tuple[MediaItem | None, str | None, int]:
    """Find the next episode to play based on viewing history.

    Returns (target_episode, action, progress_seconds).
    Actions: "resume", "next", "start", "replay"
    """
    from streamarr.models.viewing_history import ViewingHistory

    if not episodes:
        return None, None, 0

    episode_guids = [ep.guid for ep in episodes]
    ep_index = {ep.guid: i for i, ep in enumerate(episodes)}

    # Get viewing history ordered by most recently watched
    history_result = await db.execute(
        select(ViewingHistory)
        .where(
            ViewingHistory.user_guid == user_guid,
            ViewingHistory.media_item_guid.in_(episode_guids),
        )
        .order_by(ViewingHistory.last_watched_at.desc())
    )
    history_items = history_result.scalars().all()

    # 1. In-progress episode (>5% watched, not completed)
    for h in history_items:
        if not h.is_completed and h.progress_percentage > 5:
            idx = ep_index.get(h.media_item_guid)
            if idx is not None:
                return episodes[idx], "resume", h.progress_seconds

    # 2. Last completed episode → next in sequence
    for h in history_items:
        if h.is_completed:
            idx = ep_index.get(h.media_item_guid)
            if idx is not None:
                next_idx = idx + 1
                if next_idx < len(episodes):
                    return episodes[next_idx], "next", 0
                else:
                    # All watched — replay from first
                    return episodes[0], "replay", 0

    # 3. No history — start from first
    return episodes[0], "start", 0


async def _get_children(db: AsyncSession, parent_guid: uuid.UUID) -> list[MediaItem]:
    """Get child media items ordered by sequence number."""
    result = await db.execute(
        select(MediaItem)
        .where(MediaItem.parent_guid == parent_guid)
        .order_by(MediaItem.sequence_number)
    )
    return list(result.scalars().all())


async def _maybe_trigger_search(
    db: AsyncSession,
    media_item: MediaItem,
    user_guid: uuid.UUID,
) -> bool:
    """Trigger release search if not searched in the last 24 hours. Returns True if search was triggered."""
    from streamarr.worker import search_media_item_releases

    media_type = media_item.media_type.value

    # Only search for leaf content types
    is_searchable = media_type in ("MOVIES", "SONGS") or (
        media_type == "SHOWS" and media_item.parent_guid is not None
    )
    if not is_searchable:
        logger.debug("Skipping search for %s: type=%s parent=%s", media_item.title, media_type, media_item.parent_guid)
        return False

    if media_item.last_searched_at is not None:
        time_since = datetime.now(UTC) - media_item.last_searched_at
        if time_since <= timedelta(hours=24):
            logger.debug("Skipping search for %s: searched %s ago", media_item.title, time_since)
            return False

    media_item.last_searched_at = datetime.now(UTC)
    await db.commit()
    await search_media_item_releases.kiq(str(media_item.guid), str(user_guid))
    logger.info("Triggered release search for %s (%s)", media_item.title, media_item.guid)
    return True


async def _is_watched(
    db: AsyncSession,
    media_item_guid: uuid.UUID,
    user_guid: uuid.UUID,
) -> bool:
    """Check if user has a watch entry for this media item."""
    try:
        result = await db.execute(
            select(MediaWatch.guid)
            .where(
                MediaWatch.user_guid == user_guid,
                MediaWatch.media_item_guid == media_item_guid,
            )
            .limit(1)
        )
        return result.scalars().first() is not None
    except ProgrammingError:
        # The media_watch table may not exist yet (migration not run) — recover
        # the session and treat as not-watched. Any OTHER error propagates
        # rather than being silently reported as "not watched".
        await db.rollback()
        return False
