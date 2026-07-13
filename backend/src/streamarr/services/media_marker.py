"""Service for managing media markers (intro/outro/credits/song/ad)."""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import case, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.models.media_marker import MarkerSource, MarkerType, MediaMarker
from streamarr.schemas.media_marker import (
    MediaMarkerCreate,
    MediaMarkerUpdate,
    MediaMarkersForPlayer,
    PlayerMarker,
)

logger = logging.getLogger(__name__)

# Priority: manual > chromaprint > silence
SOURCE_PRIORITY = case(
    (MediaMarker.source == MarkerSource.MANUAL, 0),
    (MediaMarker.source == MarkerSource.CHROMAPRINT, 1),
    (MediaMarker.source == MarkerSource.SILENCE, 2),
    else_=3,
)

# Marker types that are unique per media item (only best source kept)
UNIQUE_MARKER_TYPES = {MarkerType.INTRO, MarkerType.OUTRO, MarkerType.CREDITS}


class MediaMarkerService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_all_markers(self, media_item_guid: uuid.UUID) -> list[MediaMarker]:
        """Get all markers for a media item."""
        result = await self.db.execute(
            select(MediaMarker)
            .where(MediaMarker.media_item_guid == media_item_guid)
            .order_by(SOURCE_PRIORITY, MediaMarker.start_seconds)
        )
        return list(result.scalars().all())

    async def get_effective_markers(self, media_item_guid: uuid.UUID) -> MediaMarkersForPlayer:
        """Get effective markers for the player.

        For unique types (intro/outro/credits): best source wins (manual > chromaprint > silence).
        For repeatable types (song/ad): all markers are returned.
        """
        all_markers = await self.get_all_markers(media_item_guid)

        result = MediaMarkersForPlayer()
        seen_unique: set[str] = set()
        player_markers: list[PlayerMarker] = []

        for marker in all_markers:
            is_unique = marker.marker_type in UNIQUE_MARKER_TYPES

            # Intros can have multiple entries - skip uniqueness for them
            if marker.marker_type == MarkerType.INTRO:
                pass  # always include
            elif is_unique and marker.marker_type in seen_unique:
                continue
            elif is_unique:
                seen_unique.add(marker.marker_type)

            player_markers.append(PlayerMarker(
                marker_type=marker.marker_type,
                start=marker.start_seconds,
                end=marker.end_seconds,
                label=marker.label,
            ))

            # Legacy fields (first intro only for backward compat)
            if marker.marker_type == MarkerType.INTRO and result.intro_start is None:
                result.intro_start = marker.start_seconds
                result.intro_end = marker.end_seconds
            elif marker.marker_type == MarkerType.OUTRO:
                result.outro_start = marker.start_seconds
                result.outro_end = marker.end_seconds
            elif marker.marker_type == MarkerType.CREDITS:
                result.credits_start = marker.start_seconds
                result.credits_end = marker.end_seconds

        result.markers = player_markers
        return result

    async def create_marker(
        self, media_item_guid: uuid.UUID, data: MediaMarkerCreate
    ) -> MediaMarker:
        """Create or upsert a marker.

        For unique types (intro/outro/credits): atomic upsert on
        (item, type, source) backed by ``uq_media_marker_unique_types``.
        For repeatable types (song/ad): always creates a new marker.
        """
        marker_type = MarkerType(data.marker_type)

        if marker_type in UNIQUE_MARKER_TYPES:
            now = datetime.now(UTC)
            stmt = (
                pg_insert(MediaMarker)
                .values(
                    media_item_guid=media_item_guid,
                    marker_type=data.marker_type,
                    source=data.source,
                    start_seconds=data.start_seconds,
                    end_seconds=data.end_seconds,
                    confidence=data.confidence,
                    label=data.label,
                    updated_at=now,
                )
                .on_conflict_do_update(
                    index_elements=["media_item_guid", "marker_type", "source"],
                    index_where=MediaMarker.marker_type.in_(UNIQUE_MARKER_TYPES),
                    set_={
                        "start_seconds": data.start_seconds,
                        "end_seconds": data.end_seconds,
                        "confidence": data.confidence,
                        "label": data.label,
                        "updated_at": now,
                    },
                )
                .returning(MediaMarker)
            )
            result = await self.db.execute(stmt)
            marker = result.scalar_one()
            await self.db.commit()
            return marker

        marker = MediaMarker(
            media_item_guid=media_item_guid,
            marker_type=data.marker_type,
            source=data.source,
            start_seconds=data.start_seconds,
            end_seconds=data.end_seconds,
            confidence=data.confidence,
            label=data.label,
        )
        self.db.add(marker)
        await self.db.commit()
        await self.db.refresh(marker)
        return marker

    async def replace_markers(
        self,
        media_item_guid: uuid.UUID,
        marker_type: MarkerType,
        source: MarkerSource,
        markers: list[MediaMarkerCreate],
    ) -> list[MediaMarker]:
        """Delete all existing markers of this type+source and create new ones.

        Used when a detection pass finds multiple segments (e.g. multiple intros).
        """
        # Delete existing
        result = await self.db.execute(
            select(MediaMarker).where(
                MediaMarker.media_item_guid == media_item_guid,
                MediaMarker.marker_type == marker_type,
                MediaMarker.source == source,
            )
        )
        for old in result.scalars().all():
            await self.db.delete(old)

        # Create new
        created = []
        for data in markers:
            marker = MediaMarker(
                media_item_guid=media_item_guid,
                marker_type=data.marker_type,
                source=data.source,
                start_seconds=data.start_seconds,
                end_seconds=data.end_seconds,
                confidence=data.confidence,
                label=data.label,
            )
            self.db.add(marker)
            created.append(marker)

        await self.db.commit()
        return created

    async def update_marker(
        self, marker_guid: uuid.UUID, data: MediaMarkerUpdate
    ) -> MediaMarker | None:
        """Update an existing marker."""
        result = await self.db.execute(
            select(MediaMarker).where(MediaMarker.guid == marker_guid)
        )
        marker = result.scalar_one_or_none()
        if not marker:
            return None

        if data.start_seconds is not None:
            marker.start_seconds = data.start_seconds
        if data.end_seconds is not None:
            marker.end_seconds = data.end_seconds
        if data.label is not None:
            marker.label = data.label
        marker.updated_at = datetime.now(UTC)

        await self.db.commit()
        await self.db.refresh(marker)
        return marker

    async def delete_marker(self, marker_guid: uuid.UUID) -> bool:
        """Delete a marker."""
        result = await self.db.execute(
            select(MediaMarker).where(MediaMarker.guid == marker_guid)
        )
        marker = result.scalar_one_or_none()
        if not marker:
            return False

        await self.db.delete(marker)
        await self.db.commit()
        return True
