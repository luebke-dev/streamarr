"""Detail response composition for media items."""

from __future__ import annotations

from streamarr.models.media import MediaItem, MediaType
from streamarr.services.library import LibraryService
from streamarr.services.media import MediaService
from streamarr.services.media_hierarchy import hierarchy_labels, is_show_tree
from streamarr.services.media_serializer import media_item_detail_payload
from streamarr.services.person import PersonService
from streamarr.services.translation import TranslationService


def _empty_hierarchy() -> dict:
    return {
        "show_title": None,
        "show_guid": None,
        "season_number": None,
        "episode_number": None,
    }


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
        hierarchy = _empty_hierarchy()
        if not is_show_tree(media_item.media_type) or not media_item.parent_guid:
            # A root item (show, movie, album, ...) has nothing above it, and
            # only the show tree has a season/episode hierarchy at all.
            return hierarchy

        load_options = {
            "load_files": False,
            "load_releases": False,
            "load_external_ids": False,
        }
        parent = await library_service.get_media_item(
            media_item.parent_guid, **load_options
        )
        if not parent:
            return hierarchy

        # Only an episode needs the show above its season; for a season the
        # parent already is the show.
        grandparent = None
        if parent.parent_guid:
            grandparent = await library_service.get_media_item(
                parent.parent_guid, **load_options
            )
        return hierarchy_labels(media_item, parent, grandparent)

    async def _cast_entries(self, media_item: MediaItem) -> list:
        cast_media_guid = None
        if media_item.media_type == MediaType.MOVIES and not media_item.parent_guid:
            cast_media_guid = media_item.guid
        elif is_show_tree(media_item.media_type):
            # A season or an episode carries no cast of its own; the show does.
            if not media_item.parent_guid:
                cast_media_guid = media_item.guid
            else:
                cast_media_guid = await MediaService(self.db).resolve_root_guid(
                    media_item.parent_guid
                )

        if not cast_media_guid:
            return []
        return await PersonService(self.db).get_cast_for_media(cast_media_guid)
