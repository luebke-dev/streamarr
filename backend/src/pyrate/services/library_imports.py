"""Library import orchestration for metadata-provider backed imports."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.models.list import List, ListItem, ListType, ListVisibility
from pyrate.models.media import MediaItem, MediaType, media_genre_table
from pyrate.plugins import registry as plugin_registry
from pyrate.schemas.list import ListCreate
from pyrate.services import system_settings
from pyrate.services.library import LibraryService
from pyrate.services.list import ListService
from pyrate.services.media import MediaService

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class LibraryExternalImportResult:
    status: str
    message: str
    media_item_guid: UUID | None = None
    already_existed: bool = False


class LibraryImportError(Exception):
    """Expected import failure that can be translated to an HTTP response."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class TrendingImportTarget:
    metadata_plugin_id: str
    fetch_method: str
    media_type: MediaType
    update_source: str
    item_type: str


class LibraryImportService:
    """Coordinates metadata imports without coupling the flow to FastAPI."""

    _trending_targets = {
        "movies": TrendingImportTarget(
            metadata_plugin_id="tmdb",
            fetch_method="get_trending_movies",
            media_type=MediaType.MOVIES,
            update_source="trending_movies",
            item_type="movie",
        ),
        "movie": TrendingImportTarget(
            metadata_plugin_id="tmdb",
            fetch_method="get_trending_movies",
            media_type=MediaType.MOVIES,
            update_source="trending_movies",
            item_type="movie",
        ),
        "shows": TrendingImportTarget(
            metadata_plugin_id="tmdb",
            fetch_method="get_trending_shows",
            media_type=MediaType.SHOWS,
            update_source="trending_shows",
            item_type="show",
        ),
        "show": TrendingImportTarget(
            metadata_plugin_id="tmdb",
            fetch_method="get_trending_shows",
            media_type=MediaType.SHOWS,
            update_source="trending_shows",
            item_type="show",
        ),
        "series": TrendingImportTarget(
            metadata_plugin_id="tmdb",
            fetch_method="get_trending_shows",
            media_type=MediaType.SHOWS,
            update_source="trending_shows",
            item_type="show",
        ),
        "games": TrendingImportTarget(
            metadata_plugin_id="igdb",
            fetch_method="get_trending_games",
            media_type=MediaType.GAMES,
            update_source="trending_games",
            item_type="game",
        ),
        "game": TrendingImportTarget(
            metadata_plugin_id="igdb",
            fetch_method="get_trending_games",
            media_type=MediaType.GAMES,
            update_source="trending_games",
            item_type="game",
        ),
    }

    _tmdb_media_types = {
        "movies": MediaType.MOVIES,
        "movie": MediaType.MOVIES,
        "shows": MediaType.SHOWS,
        "show": MediaType.SHOWS,
        "series": MediaType.SHOWS,
    }

    def __init__(self, db: AsyncSession, genre_importer=None) -> None:
        self.db = db
        self._genre_importer = genre_importer

    async def _trending_target(self, library_guid: UUID):
        library = await LibraryService(self.db).get_library(library_guid)
        if not library:
            raise LibraryImportError(
                404,
                f"Library with GUID {library_guid} not found",
            )

        library_type = library.type.lower()
        target = self._trending_targets.get(library_type)
        if not target:
            raise LibraryImportError(
                400,
                f"Trending import not supported for library type: {library.type}",
            )
        return library, library_type, target

    async def _trending_fetcher(self, target: TrendingImportTarget):
        metadata_plugin = await self._metadata_plugin(target.metadata_plugin_id)
        fetch_func = getattr(metadata_plugin, target.fetch_method, None)
        if not fetch_func:
            raise LibraryImportError(
                500,
                f"Method {target.fetch_method} not available on {target.metadata_plugin_id}",
            )
        return metadata_plugin, fetch_func

    async def _import_trending_batch(
        self,
        *,
        media_service: MediaService,
        metadata_plugin,
        target: TrendingImportTarget,
        library_guid: UUID,
        library_type: str,
        results: list[dict[str, Any]],
    ) -> tuple[list[MediaItem], int]:
        imported_items: list[MediaItem] = []
        imported_count = 0
        for item in results:
            try:
                async with self.db.begin_nested():
                    imported_item = await self._import_trending_item(
                        media_service=media_service,
                        metadata_plugin=metadata_plugin,
                        metadata_plugin_id=target.metadata_plugin_id,
                        target=target,
                        library_guid=library_guid,
                        library_type=library_type,
                        item=item,
                    )
                    if imported_item:
                        imported_items.append(imported_item)
                        if not item.get("_already_existed"):
                            imported_count += 1
            except Exception as exc:
                title = item.get("title") or item.get("name")
                logger.warning("Failed to import %s: %s", title, exc)
        return imported_items, imported_count

    async def import_trending_items(self, library_guid: UUID) -> dict[str, Any]:
        _, library_type, target = await self._trending_target(library_guid)
        metadata_plugin, fetch_func = await self._trending_fetcher(target)
        try:
            trending_data = await fetch_func()
            results = (
                trending_data.get("results", [])
                if isinstance(trending_data, dict)
                else trending_data
            )

            if not results:
                return {
                    "status": "success",
                    "message": "No trending items found",
                    "imported_count": 0,
                }

            media_service = MediaService(self.db)
            trending_list = await self._get_or_create_trending_list(target.update_source)
            imported_items, imported_count = await self._import_trending_batch(
                media_service=media_service,
                metadata_plugin=metadata_plugin,
                target=target,
                library_guid=library_guid,
                library_type=library_type,
                results=results,
            )

            await self.db.commit()

            list_delta = await self._sync_trending_list(
                trending_list=trending_list,
                imported_items=imported_items,
                item_type=target.item_type,
            )
            await self.db.commit()

            return {
                "status": "success",
                "message": f"Successfully imported {imported_count} trending items",
                "imported_count": imported_count,
                "total_found": len(results),
                "list_guid": str(trending_list.guid),
                "items_added": list_delta["items_added"],
                "items_removed": list_delta["items_removed"],
            }
        except LibraryImportError:
            await self.db.rollback()
            raise
        except Exception as exc:
            await self.db.rollback()
            logger.error("Failed to fetch trending items: %s", exc)
            raise LibraryImportError(500, "Failed to fetch trending items") from exc

    async def _tmdb_import_details(self, library, tmdb_plugin, tmdb_id: str):
        media_type = self._tmdb_media_types.get(library.type.lower())
        if not media_type:
            raise LibraryImportError(
                400,
                (
                    f"Library type '{library.type}' not supported for TMDB import. "
                    "Only movies and shows are supported."
                ),
            )

        if media_type == MediaType.MOVIES:
            details = await tmdb_plugin.get_movie_details(tmdb_id)
        elif media_type == MediaType.SHOWS:
            details = await tmdb_plugin.get_show_details(tmdb_id)
        else:
            raise LibraryImportError(
                400,
                f"TMDB does not support media type: {media_type.value}",
            )

        if not details:
            raise LibraryImportError(404, f"No details found for TMDB ID {tmdb_id}")
        return media_type, details

    async def _import_show_children_for_external_id(
        self,
        *,
        media_service: MediaService,
        tmdb_plugin,
        media_item: MediaItem,
        tmdb_id: str,
        library_guid: UUID,
        details: dict[str, Any],
    ) -> tuple[int, int]:
        return await self.import_show_seasons_and_episodes(
            media_service=media_service,
            metadata_plugin=tmdb_plugin,
            show_item=media_item,
            show_external_id=tmdb_id,
            library_guid=library_guid,
            show_details=details,
        )

    @staticmethod
    def _external_import_result(
        media_item: MediaItem,
        media_type: MediaType,
        seasons_imported: int,
        episodes_imported: int,
    ) -> LibraryExternalImportResult:
        success_message = f"Successfully imported: {media_item.title}"
        if media_type == MediaType.SHOWS and seasons_imported > 0:
            success_message += f" ({seasons_imported} seasons, {episodes_imported} episodes)"
        logger.info(success_message)
        return LibraryExternalImportResult(
            status="success",
            message=success_message,
            media_item_guid=media_item.guid,
            already_existed=False,
        )

    async def import_by_external_id(
        self,
        library_guid: UUID,
        tmdb_id: str,
    ) -> LibraryExternalImportResult:
        library = await LibraryService(self.db).get_library(library_guid)
        if not library:
            raise LibraryImportError(
                404,
                f"Library with GUID {library_guid} not found",
            )

        media_service = MediaService(self.db)
        existing = await media_service.get_by_external_id(
            provider="tmdb",
            external_id=tmdb_id,
        )
        if existing:
            logger.info("Item with TMDB ID %s already exists", tmdb_id)
            return LibraryExternalImportResult(
                status="success",
                message=f"Item already exists in library: {existing.title}",
                media_item_guid=existing.guid,
                already_existed=True,
            )

        tmdb_plugin = await self._metadata_plugin("tmdb")

        try:
            media_type, details = await self._tmdb_import_details(
                library,
                tmdb_plugin,
                tmdb_id,
            )
            media_item = await self._create_item_from_details(
                media_service=media_service,
                media_type=media_type,
                library_guid=library_guid,
                details=details,
                provider="tmdb",
                external_id=tmdb_id,
                include_backdrop=True,
            )

            seasons_imported = 0
            episodes_imported = 0
            if media_type == MediaType.SHOWS:
                seasons_imported, episodes_imported = (
                    await self._import_show_children_for_external_id(
                        media_service=media_service,
                        tmdb_plugin=tmdb_plugin,
                        media_item=media_item,
                        tmdb_id=tmdb_id,
                        library_guid=library_guid,
                        details=details,
                    )
                )

            await self.db.commit()
            return self._external_import_result(
                media_item,
                media_type,
                seasons_imported,
                episodes_imported,
            )
        except LibraryImportError:
            await self.db.rollback()
            raise
        except Exception as exc:
            await self.db.rollback()
            logger.error("Failed to import from TMDB ID %s: %s", tmdb_id, exc, exc_info=True)
            raise LibraryImportError(500, "Failed to import item") from exc

    async def _metadata_plugin(self, metadata_plugin_id: str):
        plugin_class = plugin_registry.get_plugin_class(metadata_plugin_id)
        if not plugin_class:
            provider = metadata_plugin_id.upper()
            raise LibraryImportError(
                404,
                f"{provider} plugin not found",
            )

        try:
            plugin_config: dict[str, str] = {}
            if metadata_plugin_id == "tmdb":
                tmdb_api_key = await system_settings.get_tmdb_api_key(self.db)
                if not tmdb_api_key:
                    raise LibraryImportError(
                        500,
                        "TMDB API key not configured in system settings",
                    )
                plugin_config = {"api_key": tmdb_api_key}
            elif metadata_plugin_id == "igdb":
                client_id, client_secret = await system_settings.get_igdb_credentials(
                    self.db
                )
                if not client_id or not client_secret:
                    raise LibraryImportError(
                        500,
                        "IGDB credentials not configured in system settings",
                    )
                plugin_config = {
                    "client_id": client_id,
                    "client_secret": client_secret,
                }

            return plugin_class(**plugin_config)
        except LibraryImportError:
            raise
        except Exception as exc:
            logger.error(
                "Failed to initialize metadata plugin %s: %s",
                metadata_plugin_id,
                exc,
                exc_info=True,
            )
            provider = metadata_plugin_id.upper()
            raise LibraryImportError(
                500,
                f"Failed to initialize {provider} provider",
            ) from exc

    async def _get_or_create_trending_list(self, update_source: str) -> List:
        result = await self.db.execute(
            select(List).where(List.update_source == update_source)
        )
        trending_list = result.scalar_one_or_none()
        if trending_list:
            return trending_list

        list_name_map = {
            "trending_movies": "Trending Movies",
            "trending_shows": "Trending Shows",
            "trending_games": "Trending Games",
        }
        list_name = list_name_map.get(update_source, "Trending")
        trending_list = await ListService(self.db).create(
            ListCreate(
                name=list_name,
                description=f"Automatically updated {list_name.lower()} list",
                list_type=ListType.SYSTEM,
                visibility=ListVisibility.PUBLIC,
                update_source=update_source,
                is_active=True,
            ),
            owner_guid=None,
            commit=False,
        )
        logger.info("Created trending list: %s", trending_list.name)
        return trending_list

    async def _existing_trending_item(
        self,
        *,
        media_service: MediaService,
        metadata_plugin,
        metadata_plugin_id: str,
        target: TrendingImportTarget,
        library_guid: UUID,
        external_id: str,
        title: str,
    ) -> MediaItem | None:
        existing = await media_service.get_by_external_id(
            provider=metadata_plugin_id,
            external_id=external_id,
        )
        if not existing:
            return None

        logger.debug("Item %s already exists, adding to list", title)
        if target.media_type != MediaType.SHOWS:
            return existing

        try:
            await self.import_show_seasons_and_episodes(
                media_service=media_service,
                metadata_plugin=metadata_plugin,
                show_item=existing,
                show_external_id=external_id,
                library_guid=library_guid,
            )
            logger.info("Imported seasons and episodes for existing show %s", title)
        except Exception as exc:
            logger.warning("Failed to import seasons/episodes for %s: %s", title, exc)
        return existing

    async def _import_show_children_for_trending(
        self,
        *,
        media_service: MediaService,
        metadata_plugin,
        media_item: MediaItem,
        external_id: str,
        library_guid: UUID,
        details: dict[str, Any],
        title: str,
    ) -> None:
        try:
            await self.import_show_seasons_and_episodes(
                media_service=media_service,
                metadata_plugin=metadata_plugin,
                show_item=media_item,
                show_external_id=external_id,
                library_guid=library_guid,
                show_details=details,
            )
            logger.info("Imported seasons and episodes for %s", title)
        except Exception as exc:
            logger.warning("Failed to import seasons/episodes for %s: %s", title, exc)

    async def _import_trending_item(
        self,
        *,
        media_service: MediaService,
        metadata_plugin,
        metadata_plugin_id: str,
        target: TrendingImportTarget,
        library_guid: UUID,
        library_type: str,
        item: dict[str, Any],
    ) -> MediaItem | None:
        external_id = str(item.get("id"))
        title = item.get("title") or item.get("name")
        if not title or not external_id:
            return None

        existing = await self._existing_trending_item(
            media_service=media_service,
            metadata_plugin=metadata_plugin,
            metadata_plugin_id=metadata_plugin_id,
            target=target,
            library_guid=library_guid,
            external_id=external_id,
            title=title,
        )
        if existing:
            item["_already_existed"] = True
            return existing

        details = await self._fetch_details_for_trending_item(
            metadata_plugin=metadata_plugin,
            library_type=library_type,
            external_id=external_id,
            item=item,
        )
        media_item = await self._create_item_from_details(
            media_service=media_service,
            media_type=target.media_type,
            library_guid=library_guid,
            details=details,
            provider=metadata_plugin_id,
            external_id=external_id,
        )

        await self._import_additional_external_ids(
            media_service=media_service,
            metadata_plugin=metadata_plugin,
            metadata_plugin_id=metadata_plugin_id,
            media_item=media_item,
            external_id=external_id,
            library_type=library_type,
        )

        if target.media_type == MediaType.SHOWS:
            await self._import_show_children_for_trending(
                media_service=media_service,
                metadata_plugin=metadata_plugin,
                media_item=media_item,
                external_id=external_id,
                library_guid=library_guid,
                details=details,
                title=title,
            )

        logger.info("Imported %s from %s", title, metadata_plugin_id)
        return media_item

    async def _fetch_details_for_trending_item(
        self,
        *,
        metadata_plugin,
        library_type: str,
        external_id: str,
        item: dict[str, Any],
    ) -> dict[str, Any]:
        if library_type in ("movies", "movie"):
            return await metadata_plugin.get_movie_details(external_id)
        if library_type in ("shows", "show", "series"):
            return await metadata_plugin.get_show_details(external_id)
        return item

    async def _create_item_from_details(
        self,
        *,
        media_service: MediaService,
        media_type: MediaType,
        library_guid: UUID,
        details: dict[str, Any],
        provider: str,
        external_id: str,
        include_backdrop: bool = False,
    ) -> MediaItem:
        title = details.get("title") or details.get("name")
        release_date = self._parse_release_date(
            details.get("release_date")
            or details.get("first_air_date")
            or details.get("first_release_date"),
            title=title,
        )
        media_item = await media_service.create_media_item(
            media_type=media_type,
            title=title,
            library_guid=library_guid,
            description=details.get("overview") or details.get("summary"),
            poster_path=details.get("poster_path") or details.get("cover", {}).get("url"),
            backdrop_path=details.get("backdrop_path") if include_backdrop else None,
            release_date=release_date,
            metadata=details,
            commit=False,
        )
        await media_service.add_external_id(
            media_item_guid=media_item.guid,
            provider=provider,
            external_id=external_id,
            commit=False,
        )

        genre_ids = details.get("genre_ids") or details.get("genres", [])
        if genre_ids:
            if self._genre_importer:
                await self._genre_importer(self.db, media_item.guid, genre_ids)
            else:
                await self.import_genres_for_media(media_item.guid, genre_ids)

        return media_item

    async def _import_additional_external_ids(
        self,
        *,
        media_service: MediaService,
        metadata_plugin,
        metadata_plugin_id: str,
        media_item: MediaItem,
        external_id: str,
        library_type: str,
    ) -> None:
        if metadata_plugin_id != "tmdb":
            return

        try:
            if library_type in ("movies", "movie"):
                external_ids_data = await metadata_plugin.get_movie_external_ids(
                    external_id
                )
            elif library_type in ("shows", "show", "series"):
                external_ids_data = await metadata_plugin.get_show_external_ids(
                    external_id
                )
            else:
                external_ids_data = {}

            imdb_id = external_ids_data.get("imdb_id")
            if imdb_id:
                await media_service.add_external_id(
                    media_item_guid=media_item.guid,
                    provider="imdb",
                    external_id=imdb_id,
                    commit=False,
                )

            tvdb_id = external_ids_data.get("tvdb_id")
            if tvdb_id:
                await media_service.add_external_id(
                    media_item_guid=media_item.guid,
                    provider="tvdb",
                    external_id=str(tvdb_id),
                    commit=False,
                )

            logger.debug(
                "Added external IDs for %s: IMDb=%s, TVDb=%s",
                media_item.title,
                imdb_id,
                tvdb_id,
            )
        except Exception as exc:
            logger.warning(
                "Failed to fetch external IDs for %s: %s",
                media_item.title,
                exc,
            )

    async def _sync_trending_list(
        self,
        *,
        trending_list: List,
        imported_items: list[MediaItem],
        item_type: str,
    ) -> dict[str, int]:
        current_items_result = await self.db.execute(
            select(ListItem).where(ListItem.list_guid == trending_list.guid)
        )
        current_items = current_items_result.scalars().all()
        current_by_media_guid = {str(item.item_guid): item for item in current_items}
        new_item_guids = {str(item.guid) for item in imported_items}

        items_to_remove = set(current_by_media_guid) - new_item_guids
        items_to_add = new_item_guids - set(current_by_media_guid)

        if items_to_remove:
            stale_list_item_guids = [
                current_by_media_guid[g].guid for g in items_to_remove
            ]
            await self.db.execute(
                sa_delete(ListItem).where(ListItem.guid.in_(stale_list_item_guids))
            )
            logger.info(
                "Removed %s stale items from trending list",
                len(stale_list_item_guids),
            )

        new_list_items = [
            ListItem(
                list_guid=trending_list.guid,
                item_type=item_type,
                item_guid=media_item.guid,
            )
            for media_item in imported_items
            if str(media_item.guid) in items_to_add
        ]
        if new_list_items:
            self.db.add_all(new_list_items)
            logger.info("Added %s items to trending list", len(new_list_items))

        trending_list.item_count = (
            len(current_items) - len(items_to_remove) + len(new_list_items)
        )
        return {
            "items_added": len(new_list_items),
            "items_removed": len(items_to_remove),
        }

    async def import_genres_for_media(
        self,
        media_item_guid: UUID,
        genre_data: list[Any],
    ) -> None:
        from pyrate.models.genre import Genre

        insert_stmt = self._dialect_insert()

        for genre_info in genre_data:
            if isinstance(genre_info, dict):
                genre_id = genre_info.get("id")
                genre_name = genre_info.get("name")
            else:
                genre_id = genre_info
                genre_name = None

            if not genre_id:
                continue

            result = await self.db.execute(select(Genre).where(Genre.id == genre_id))
            genre = result.scalar_one_or_none()

            if not genre and genre_name:
                stmt = (
                    insert_stmt(Genre)
                    .values(id=genre_id, name=genre_name)
                    .on_conflict_do_nothing(index_elements=["name"])
                )
                await self.db.execute(stmt)
                await self.db.flush()

                result = await self.db.execute(select(Genre).where(Genre.id == genre_id))
                genre = result.scalar_one_or_none()

                if genre:
                    logger.info("Created genre: %s - %s", genre_id, genre_name)

            if genre or genre_name:
                try:
                    await self.db.execute(
                        insert_stmt(media_genre_table)
                        .values(media_item_guid=media_item_guid, genre_id=genre_id)
                        .on_conflict_do_nothing()
                    )
                except Exception as exc:
                    logger.debug("Genre %s association error: %s", genre_id, exc)

    async def import_show_seasons_and_episodes(
        self,
        *,
        media_service: MediaService,
        metadata_plugin,
        show_item: MediaItem,
        show_external_id: str,
        library_guid: UUID,
        show_details: dict[str, Any] | None = None,
    ) -> tuple[int, int]:
        if show_details is None:
            show_details = await metadata_plugin.get_show_details(show_external_id)

        seasons = show_details.get("seasons", [])
        logger.info("Found %s seasons for show %s", len(seasons), show_item.title)

        seasons_imported = 0
        episodes_imported = 0
        for season_data in seasons:
            season_number = season_data.get("season_number")
            if season_number is None or season_number == 0:
                continue

            try:
                season_details = await metadata_plugin.get_show_season(
                    show_external_id,
                    str(season_number),
                )
                if not season_details:
                    logger.warning("Could not fetch details for season %s", season_number)
                    continue

                season_item = await self._get_or_create_season(
                    media_service=media_service,
                    show_item=show_item,
                    library_guid=library_guid,
                    season_number=season_number,
                    season_details=season_details,
                )
                if season_item["created"]:
                    seasons_imported += 1

                imported = await self._import_episodes(
                    media_service=media_service,
                    season_item=season_item["item"],
                    season_number=season_number,
                    library_guid=library_guid,
                    episodes=season_details.get("episodes", []),
                )
                episodes_imported += imported
            except Exception as exc:
                logger.warning("Failed to import season %s: %s", season_number, exc)
                continue

        await self.db.flush()
        return seasons_imported, episodes_imported

    async def _get_or_create_season(
        self,
        *,
        media_service: MediaService,
        show_item: MediaItem,
        library_guid: UUID,
        season_number: int,
        season_details: dict[str, Any],
    ) -> dict[str, Any]:
        season_item = await media_service.get_child_by_sequence(
            parent_guid=show_item.guid,
            sequence_number=season_number,
        )
        if season_item:
            logger.info(
                "Season %s already exists for %s, skipping create",
                season_number,
                show_item.title,
            )
            return {"item": season_item, "created": False}

        season_item = await media_service.create_media_item(
            media_type=MediaType.SHOWS,
            title=season_details.get("name", f"Season {season_number}"),
            library_guid=library_guid,
            parent_guid=show_item.guid,
            sequence_number=season_number,
            description=season_details.get("overview"),
            poster_path=season_details.get("poster_path"),
            release_date=self._parse_release_date(
                season_details.get("air_date"),
                title=f"{show_item.title} season {season_number}",
            ),
            metadata=season_details,
            commit=False,
        )

        season_tmdb_id = season_details.get("id")
        if season_tmdb_id:
            await media_service.add_external_id(
                media_item_guid=season_item.guid,
                provider="tmdb",
                external_id=str(season_tmdb_id),
                commit=False,
            )
        return {"item": season_item, "created": True}

    async def _import_episodes(
        self,
        *,
        media_service: MediaService,
        season_item: MediaItem,
        season_number: int,
        library_guid: UUID,
        episodes: list[dict[str, Any]],
    ) -> int:
        logger.info("Found %s episodes in season %s", len(episodes), season_number)
        imported = 0
        for episode_data in episodes:
            episode_number = episode_data.get("episode_number")
            if episode_number is None:
                continue

            episode_item = await media_service.get_child_by_sequence(
                parent_guid=season_item.guid,
                sequence_number=episode_number,
            )
            if episode_item:
                logger.debug(
                    "Episode %s in season %s already exists, skipping",
                    episode_number,
                    season_number,
                )
                continue

            episode_item = await media_service.create_media_item(
                media_type=MediaType.SHOWS,
                title=episode_data.get("name", f"Episode {episode_number}"),
                library_guid=library_guid,
                parent_guid=season_item.guid,
                sequence_number=episode_number,
                description=episode_data.get("overview"),
                poster_path=episode_data.get("still_path"),
                release_date=self._parse_release_date(
                    episode_data.get("air_date"),
                    title=episode_data.get("name", f"Episode {episode_number}"),
                ),
                metadata=episode_data,
                commit=False,
            )
            imported += 1

            episode_tmdb_id = episode_data.get("id")
            if episode_tmdb_id:
                await media_service.add_external_id(
                    media_item_guid=episode_item.guid,
                    provider="tmdb",
                    external_id=str(episode_tmdb_id),
                    commit=False,
                )
        return imported

    @staticmethod
    def _parse_release_date(value: Any, *, title: str | None = None) -> date | None:
        if not value:
            return None
        try:
            if isinstance(value, str):
                return datetime.fromisoformat(value).date()
            if isinstance(value, int):
                return datetime.fromtimestamp(value).date()
            if isinstance(value, datetime):
                return value.date()
            if isinstance(value, date):
                return value
        except (ValueError, AttributeError, OSError, OverflowError) as exc:
            logger.warning("Failed to parse release date for %s: %s", title, exc)
        return None

    def _dialect_insert(self):
        bind = self.db.get_bind()
        if bind.dialect.name == "sqlite":
            from sqlalchemy.dialects.sqlite import insert

            return insert

        from sqlalchemy.dialects.postgresql import insert

        return insert
