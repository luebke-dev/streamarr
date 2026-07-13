"""Detail response composition for media items."""

from __future__ import annotations

from streamarr.models.media import MediaItem, MediaType
from streamarr.services.library import LibraryService
from streamarr.services.media import MediaService
from streamarr.services.media_serializer import media_item_detail_payload
from streamarr.services.person import PersonService
from streamarr.services.translation import TranslationService


class MediaDetailService:
    def __init__(self, db) -> None:
        self.db = db

    async def build_detail_payload(
        self,
        media_item: MediaItem,
        *,
        library_service: LibraryService,
        ui_language: str | None,
        load_files: bool,
        load_releases: bool,
        load_external_ids: bool,
    ) -> dict:
        hierarchy = await self._show_hierarchy(media_item, library_service)
        if load_releases and media_item.releases:
            await library_service.rescore_releases(media_item, media_item.releases)

        item_dict = media_item_detail_payload(
            media_item,
            load_files=load_files,
            load_releases=load_releases,
            load_external_ids=load_external_ids,
            cast_entries=await self._cast_entries(media_item),
            **hierarchy,
        )
        translated = await TranslationService(self.db).get_translated_fields(
            media_item,
            ui_language,
        )
        item_dict["title"] = translated["title"]
        item_dict["description"] = translated["description"]
        item_dict["tagline"] = translated["tagline"]
        return item_dict

    async def _show_hierarchy(
        self,
        media_item: MediaItem,
        library_service: LibraryService,
    ) -> dict:
        hierarchy = {
            "show_title": None,
            "show_guid": None,
            "season_number": None,
            "episode_number": None,
        }
        if media_item.media_type != MediaType.SHOWS or not media_item.parent_guid:
            return hierarchy

        hierarchy["episode_number"] = media_item.sequence_number
        season = await library_service.get_media_item(
            media_item.parent_guid,
            load_files=False,
            load_releases=False,
            load_external_ids=False,
        )
        if not season or not season.parent_guid:
            return hierarchy

        hierarchy["season_number"] = season.sequence_number
        show = await library_service.get_media_item(
            season.parent_guid,
            load_files=False,
            load_releases=False,
            load_external_ids=False,
        )
        if show:
            hierarchy["show_title"] = show.title
            hierarchy["show_guid"] = show.guid
        return hierarchy

    async def _cast_entries(self, media_item: MediaItem) -> list:
        cast_media_guid = None
        if media_item.media_type == MediaType.MOVIES and not media_item.parent_guid:
            cast_media_guid = media_item.guid
        elif media_item.media_type == MediaType.SHOWS:
            if not media_item.parent_guid:
                cast_media_guid = media_item.guid
            else:
                cast_media_guid = await MediaService(self.db).resolve_root_guid(
                    media_item.parent_guid
                )

        if not cast_media_guid:
            return []
        return await PersonService(self.db).get_cast_for_media(cast_media_guid)
