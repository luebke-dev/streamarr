"""Show resume episode selection."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select

from pyrate.models.media import MediaItem, MediaType
from pyrate.models.viewing_history import ViewingHistory
from pyrate.services.library import LibraryService, MEDIA_ITEM_LOAD_OPTIONS


class ShowResumeError(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(slots=True)
class ShowResumeResult:
    episode: MediaItem
    action: str
    season_number: int
    episode_number: int
    progress_seconds: float


class ShowResumeService:
    def __init__(self, db) -> None:
        self.db = db
        self.library_service = LibraryService(db)
        self._episode_rows: list[tuple[int, int, MediaItem]] = []

    async def get_show(self, show_guid: UUID) -> MediaItem | None:
        result = await self.db.execute(
            select(MediaItem).where(
                MediaItem.guid == show_guid,
                MediaItem.media_type == MediaType.SHOWS,
                MediaItem.parent_guid.is_(None),
            )
        )
        return result.scalars().first()

    async def get_resume_episode(
        self,
        show_guid: UUID,
        *,
        user_guid: UUID,
    ) -> ShowResumeResult:
        episode_rows = await self._ordered_episode_rows(show_guid)
        self._episode_rows = episode_rows
        episode_guids = [episode.guid for _, _, episode in episode_rows]
        ep_index_by_guid = {
            episode.guid: index for index, (_, _, episode) in enumerate(episode_rows)
        }

        history_items = await self._history_items(user_guid, episode_guids)
        in_progress = self._in_progress_episode(history_items, ep_index_by_guid)
        if in_progress is not None:
            sn, en, episode, history = in_progress
            return ShowResumeResult(
                episode=episode,
                action="resume",
                season_number=sn,
                episode_number=en,
                progress_seconds=history.progress_seconds,
            )

        next_episode = self._next_after_completed(history_items, ep_index_by_guid)
        if next_episode is not None:
            sn, en, episode, action = next_episode
            return ShowResumeResult(
                episode=episode,
                action=action,
                season_number=sn,
                episode_number=en,
                progress_seconds=0,
            )

        sn, en, episode = episode_rows[0]
        return ShowResumeResult(
            episode=episode,
            action="start",
            season_number=sn,
            episode_number=en,
            progress_seconds=0,
        )

    async def _ordered_episode_rows(
        self,
        show_guid: UUID,
    ) -> list[tuple[int, int, MediaItem]]:
        seasons = await self.library_service.get_children(
            show_guid,
            order_by_sequence=True,
        )
        if not seasons:
            raise ShowResumeError("No seasons found for this show")

        episodes_by_season = await self.library_service.get_children_bulk(
            [season.guid for season in seasons],
            order_by_sequence=True,
        )
        episode_meta: list[tuple[int, int, UUID]] = []
        for season in seasons:
            for episode in episodes_by_season.get(season.guid, []):
                episode_meta.append(
                    (
                        season.sequence_number or 0,
                        episode.sequence_number or 0,
                        episode.guid,
                    )
                )

        if not episode_meta:
            raise ShowResumeError("No episodes found for this show")

        episode_meta.sort(key=lambda row: (row[0], row[1]))
        episode_guids = [guid for _, _, guid in episode_meta]
        result = await self.db.execute(
            select(MediaItem)
            .where(MediaItem.guid.in_(episode_guids))
            .options(*MEDIA_ITEM_LOAD_OPTIONS)
        )
        ep_by_guid = {episode.guid: episode for episode in result.scalars().all()}
        episode_rows = [
            (sn, en, ep_by_guid[guid])
            for sn, en, guid in episode_meta
            if guid in ep_by_guid
        ]
        if not episode_rows:
            raise ShowResumeError("No episodes found for this show")
        return episode_rows

    async def _history_items(
        self,
        user_guid: UUID,
        episode_guids: list[UUID],
    ) -> list[ViewingHistory]:
        result = await self.db.execute(
            select(ViewingHistory)
            .where(
                ViewingHistory.user_guid == user_guid,
                ViewingHistory.media_item_guid.in_(episode_guids),
            )
            .order_by(ViewingHistory.last_watched_at.desc())
        )
        return list(result.scalars().all())

    def _in_progress_episode(
        self,
        history_items: list[ViewingHistory],
        ep_index_by_guid: dict[UUID, int],
    ):
        for history in history_items:
            if not history.is_completed and history.progress_percentage > 5:
                index = ep_index_by_guid.get(history.media_item_guid)
                if index is not None:
                    return (*self._episode_rows[index], history)
        return None

    def _next_after_completed(
        self,
        history_items: list[ViewingHistory],
        ep_index_by_guid: dict[UUID, int],
    ):
        for history in history_items:
            if history.is_completed:
                index = ep_index_by_guid.get(history.media_item_guid)
                if index is not None:
                    next_index = index + 1
                    if next_index < len(self._episode_rows):
                        return (*self._episode_rows[next_index], "next")
                    return (*self._episode_rows[0], "replay")
        return None
