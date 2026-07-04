"""Release search service - orchestrates searching, matching, and persisting releases."""

import logging
import re
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from pyrate.libraries import get_plugin_instance
from pyrate.models.media import (
    MediaItem,
    MediaRelease,
    MediaReleaseLink,
    MediaType,
)
from pyrate.services.indexer import IndexerService
from pyrate.services.release_matcher import ReleaseMatcher

logger = logging.getLogger(__name__)


class ReleaseSearchService:
    """Orchestrates release search, matching, deduplication, and persistence."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def search_and_store_releases(
        self,
        media_item_guid: str,
        user_guid: str | None = None,
        *,
        force: bool = False,
    ) -> None:
        """Search for releases for a media item and store matching ones.

        Args:
            media_item_guid: GUID of the media item to search releases for
            user_guid: Optional GUID of the user who triggered the search
            force: When True (deliberate favorites backfill / upgrade scan)
                re-search even if releases-with-links already exist and do
                not reject a root show — caller targets leaves itself.
        """
        logger.info("Starting release search for media item %s", media_item_guid)

        # Load media item with relationships
        media_item = await self._load_media_item(media_item_guid)
        if not media_item:
            logger.warning("Media item %s not found", media_item_guid)
            return

        # Check if item already has releases with download links
        if not force and self._has_releases_with_links(media_item):
            return

        # Validate media type is searchable
        if not self._is_searchable(media_item, force=force):
            return

        # Extract external IDs
        external_ids_info = self._extract_external_ids(media_item)

        # Validate required external IDs
        if not self._validate_external_ids(media_item, external_ids_info):
            return

        # Resolve show context for episodes
        show_context = await self._resolve_show_context(media_item, external_ids_info)

        # Search indexers for releases
        indexer_service = IndexerService(self.db)
        releases_data = await self._search_indexers(
            media_item, indexer_service, external_ids_info, show_context
        )

        if releases_data is None:
            return

        # Build matching context and filter releases
        matching_releases = await self._match_releases(
            media_item, releases_data, external_ids_info, show_context
        )

        logger.info(
            "Filtered to %s matching releases (rejected %s)",
            len(matching_releases),
            len(releases_data) - len(matching_releases),
        )

        # Persist releases to database
        release_count = await self._persist_releases(
            media_item, matching_releases
        )

        # Update last_searched_at
        media_item.last_searched_at = datetime.now(UTC)
        await self.db.commit()

        logger.info(
            "Successfully stored %s matching releases for media item %s (filtered from %s raw results)",
            release_count,
            media_item.title,
            len(releases_data),
        )

        if release_count > 0:
            logger.info(
                "Found %s releases for %s — ready for on-demand download",
                release_count,
                media_item.title,
            )

        # Publish WebSocket event for real-time UI updates
        await self._publish_releases_updated(media_item, release_count, len(releases_data))

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    async def _load_media_item(self, media_item_guid: str) -> MediaItem | None:
        # parent is eager-loaded so book search can read parent.title (author)
        # without triggering a lazy load mid-async-flow.
        result = await self.db.execute(
            select(MediaItem)
            .where(MediaItem.guid == media_item_guid)
            .options(
                selectinload(MediaItem.external_ids),
                selectinload(MediaItem.releases).selectinload(MediaRelease.links),
                selectinload(MediaItem.parent),
            )
        )
        return result.scalar_one_or_none()

    def _has_releases_with_links(self, media_item: MediaItem) -> bool:
        """Check if item already has releases WITH download links."""
        releases_with_links = [
            r for r in (media_item.releases or []) if r.links
        ]
        if releases_with_links:
            logger.info(
                "Media item %s already has %s releases with links, skipping search",
                media_item.guid,
                len(releases_with_links),
            )
            return True

        if media_item.releases:
            logger.info(
                "Media item %s has %s releases but none have links, re-searching",
                media_item.guid,
                len(media_item.releases),
            )
        return False

    def _is_searchable(
        self, media_item: MediaItem, *, force: bool = False
    ) -> bool:
        """Check if this media type supports release search."""
        if media_item.media_type not in [MediaType.MOVIES, MediaType.SHOWS, MediaType.SONGS, MediaType.BOOKS, MediaType.GAMES]:
            logger.info(
                "Media item %s is type %s, skipping release search",
                media_item.guid,
                media_item.media_type,
            )
            return False

        # For series, only search for items with a parent (episodes/seasons).
        # A forced backfill/upgrade may target a root show (season-pack);
        # let it through — the downstream pipeline no-ops gracefully if it
        # can't resolve a season/episode.
        if (
            not force
            and media_item.media_type == MediaType.SHOWS
            and not media_item.parent_guid
        ):
            logger.info(
                "Media item %s is a root show, skipping release search",
                media_item.guid,
            )
            return False

        return True

    def _extract_external_ids(self, media_item: MediaItem) -> dict[str, str | None]:
        """Extract external IDs from a media item."""
        ids: dict[str, str | None] = {
            "tmdb": None,
            "imdb": None,
            "tvdb": None,
            "spotify": None,
            "openlibrary": None,
            "isbn": None,
            "igdb": None,
        }
        for ext_id in media_item.external_ids:
            if ext_id.provider in ids:
                ids[ext_id.provider] = ext_id.external_id
        return ids

    def _validate_external_ids(
        self, media_item: MediaItem, ids: dict[str, str | None]
    ) -> bool:
        """Validate that required external IDs are present."""
        if media_item.media_type in [MediaType.MOVIES, MediaType.SHOWS] and not ids["tmdb"]:
            logger.warning(
                "No TMDB ID found for media item %s, cannot search releases",
                media_item.title,
            )
            return False
        if media_item.media_type == MediaType.SONGS and not ids["spotify"]:
            logger.warning(
                "No Spotify ID found for song %s, cannot search releases",
                media_item.title,
            )
            return False
        # Books and games always valid — search by title
        if media_item.media_type in [MediaType.BOOKS, MediaType.GAMES]:
            return True
        return True

    async def _resolve_show_context(
        self, media_item: MediaItem, ids: dict[str, str | None]
    ) -> dict[str, Any]:
        """For episodes, resolve the parent show, season/episode numbers, and TVDB ID."""
        context: dict[str, Any] = {
            "show": None,
            "show_title": None,
            "season_number": None,
            "episode_number": None,
        }

        if media_item.media_type != MediaType.SHOWS or not media_item.parent_guid:
            return context

        # Traverse up the parent chain to the root show
        show = media_item
        while show.parent_guid:
            result = await self.db.execute(
                select(MediaItem)
                .where(MediaItem.guid == show.parent_guid)
                .options(selectinload(MediaItem.external_ids))
            )
            show = result.scalar_one_or_none()
            if not show:
                break

        # Get TVDB/IMDB ID from show
        if show:
            context["show"] = show
            context["show_title"] = show.title
            for ext_id in show.external_ids:
                if ext_id.provider == "tvdb":
                    ids["tvdb"] = ext_id.external_id
                elif ext_id.provider == "imdb":
                    ids["imdb"] = ext_id.external_id

            if not ids["tvdb"]:
                logger.info(
                    "No TVDB ID found for show %s, will use title-based search for episode",
                    show.title,
                )

        # Episode number from the item itself
        context["episode_number"] = media_item.sequence_number

        # Season number from parent
        if media_item.parent_guid:
            season_result = await self.db.execute(
                select(MediaItem).where(MediaItem.guid == media_item.parent_guid)
            )
            season = season_result.scalar_one_or_none()
            if season:
                context["season_number"] = season.sequence_number

                # Fallback: extract season number from title
                if context["season_number"] is None and season.title:
                    m = re.search(
                        r"[Ss]eason\s+(\d+)", season.title
                    ) or re.search(r"\bS(\d{1,2})\b", season.title)
                    if m:
                        context["season_number"] = int(m.group(1))
                        logger.info(
                            "Derived season number %s from season title '%s'",
                            context["season_number"],
                            season.title,
                        )

        return context

    async def _search_indexers(
        self,
        media_item: MediaItem,
        indexer_service: IndexerService,
        ids: dict[str, str | None],
        show_context: dict[str, Any],
    ) -> list[dict[str, Any]] | None:
        """Query indexers based on media type. Returns None if search cannot proceed."""
        if media_item.media_type == MediaType.MOVIES:
            return await self._search_movie_releases(media_item, indexer_service, ids)
        elif media_item.media_type == MediaType.SHOWS:
            return await self._search_show_releases(
                media_item, indexer_service, ids, show_context
            )
        elif media_item.media_type == MediaType.SONGS:
            return await self._search_music_releases(media_item, indexer_service, ids)
        elif media_item.media_type == MediaType.BOOKS:
            return await self._search_book_releases(media_item, indexer_service, ids)
        elif media_item.media_type == MediaType.GAMES:
            return await self._search_game_releases(media_item, indexer_service, ids)
        else:
            logger.warning(
                "Unsupported media type for release search: %s",
                media_item.media_type,
            )
            return None

    async def _search_movie_releases(
        self,
        media_item: MediaItem,
        indexer_service: IndexerService,
        ids: dict[str, str | None],
    ) -> list[dict[str, Any]]:
        releases_data: list[dict[str, Any]] = []
        if ids["imdb"]:
            logger.info("Searching for movie releases by IMDB ID: %s", ids["imdb"])
            releases_data = await indexer_service.search_movies(imdb_id=ids["imdb"])

        if not releases_data:
            year = None
            if media_item.release_date:
                year = media_item.release_date.year
            search_query = f"{media_item.title} {year}" if year else media_item.title
            logger.info("Searching for movie releases by title: %s", search_query)
            releases_data = await indexer_service.search_movies(query=search_query)

        return releases_data

    async def _search_show_releases(
        self,
        media_item: MediaItem,
        indexer_service: IndexerService,
        ids: dict[str, str | None],
        show_context: dict[str, Any],
    ) -> list[dict[str, Any]] | None:
        season_number = show_context["season_number"]
        episode_number = show_context["episode_number"]
        show_title = show_context["show_title"]
        show = show_context["show"]

        if season_number is None or episode_number is None:
            logger.warning(
                "Episode %s missing season/episode numbers (season=%s, episode=%s), cannot search",
                media_item.guid,
                season_number,
                episode_number,
            )
            return None

        if not show_title:
            show_title = show.title if show else media_item.title

        search_query = f"{show_title} S{season_number:02d}E{episode_number:02d}"
        logger.info(
            "Searching for episode releases: %s (tvdb=%s, imdb=%s)",
            search_query,
            ids["tvdb"],
            ids["imdb"],
        )
        return await indexer_service.search_shows(
            query=search_query,
            tvdb_id=ids["tvdb"],
            imdb_id=ids["imdb"],
            season=str(season_number),
            episode=str(episode_number),
        )

    async def _search_music_releases(
        self,
        media_item: MediaItem,
        indexer_service: IndexerService,
        ids: dict[str, str | None],
    ) -> list[dict[str, Any]]:
        artist_name = media_item.description or ""
        song_title = media_item.title
        album_title = None

        if media_item.parent_guid:
            parent_result = await self.db.execute(
                select(MediaItem).where(MediaItem.guid == media_item.parent_guid)
            )
            parent = parent_result.scalar_one_or_none()
            if parent:
                album_title = parent.title

        search_query = f"{artist_name} {album_title or song_title}".strip()
        logger.info(
            "Searching for music releases: artist=%s, album=%s, query=%s",
            artist_name,
            album_title,
            search_query,
        )
        releases_data = await indexer_service.search_music_releases(
            query=search_query,
            artist=artist_name or None,
            album=album_title,
        )

        if ids["spotify"]:
            try:
                spotify_releases = await indexer_service.search_music(
                    spotify_id=ids["spotify"],
                    query=search_query if not ids["spotify"] else None,
                )
                releases_data.extend(spotify_releases)
            except Exception as e:
                logger.debug("Spotify music search failed: %s", e)

        return releases_data

    async def _search_book_releases(
        self,
        media_item: MediaItem,
        indexer_service: IndexerService,
        ids: dict[str, str | None],
    ) -> list[dict[str, Any]]:
        """Search for book/audiobook releases via indexers.

        Authors live as the *parent* media item (media_type=AUTHORS), not on
        the book itself. Earlier code reused ``description`` as a stand-in,
        which produced absurd queries like ``"<200-word synopsis> <title>"``
        and never returned results. Pull the author from the parent instead
        and fall back to a title-only search if the parent isn't available.
        """
        title = media_item.title or ""
        author = media_item.parent.title if media_item.parent else ""

        search_query = f"{author} {title}".strip() if author else title
        logger.info(
            "Searching for book releases: author=%s, title=%s, query=%s",
            author, title, search_query,
        )
        return await indexer_service.search_books(
            query=search_query,
            author=author or None,
            title=title,
        )

    async def _search_game_releases(
        self,
        media_item: MediaItem,
        indexer_service: IndexerService,
        ids: dict[str, str | None],
    ) -> list[dict[str, Any]]:
        """Search for game releases via indexers."""
        search_query = media_item.title
        year = None
        if media_item.release_date:
            year = media_item.release_date.year

        logger.info(
            "Searching for game releases: %s (igdb=%s)",
            search_query, ids.get("igdb"),
        )
        return await indexer_service.search_games(
            query=search_query,
        )

    async def _game_platform_slugs(self, media_item: MediaItem) -> set[str]:
        """Canonical platform slugs of a game (from its IGDB platforms).

        Empty set means "unknown" — the matcher then falls back to title-only
        matching rather than rejecting everything.
        """
        from pyrate.models.platform import Platform
        from pyrate.services.game_platforms import normalize_platforms

        try:
            result = await self.db.execute(
                select(Platform.name)
                .select_from(MediaItem)
                .join(MediaItem.platforms)
                .where(MediaItem.guid == media_item.guid)
            )
            names = list(result.scalars().all())
        except Exception as exc:  # noqa: BLE001 — never break search on this
            logger.warning(
                "Could not load platforms for game %s: %s", media_item.guid, exc
            )
            return set()
        return normalize_platforms(names)

    async def _match_releases(
        self,
        media_item: MediaItem,
        releases_data: list[dict[str, Any]],
        ids: dict[str, str | None],
        show_context: dict[str, Any],
    ) -> list[tuple[dict[str, Any], Any]]:
        """Apply release matching filter based on media type."""
        logger.info("Found %s raw releases, filtering for matches...", len(releases_data))

        external_ids = {}
        if ids["imdb"]:
            external_ids["imdb"] = ids["imdb"]
        if ids["tvdb"]:
            external_ids["tvdb"] = ids["tvdb"]

        # Resolve year / release_date for matching
        media_year, media_release_date_str = await self._resolve_year(
            media_item, show_context
        )

        if media_year:
            logger.info("Using year %s for release matching", media_year)
        else:
            logger.warning("No year found for release matching of %s", media_item.title)

        if media_item.media_type == MediaType.MOVIES:
            return ReleaseMatcher.filter_matching_releases(
                releases=releases_data,
                media_title=media_item.title,
                media_year=media_year,
                external_ids=external_ids,
                min_score=0.0,
                media_release_date=media_release_date_str,
            )
        elif media_item.media_type == MediaType.SONGS:
            return self._match_music_releases(
                media_item, releases_data, media_year
            )
        elif media_item.media_type == MediaType.GAMES:
            return ReleaseMatcher.filter_matching_releases(
                releases=releases_data,
                media_title=media_item.title,
                media_year=media_year,
                external_ids=external_ids,
                min_score=0.0,
                media_release_date=media_release_date_str,
                is_game=True,
                game_platforms=await self._game_platform_slugs(media_item),
            )
        elif media_item.media_type == MediaType.BOOKS:
            return ReleaseMatcher.filter_matching_releases(
                releases=releases_data,
                media_title=media_item.title,
                media_year=media_year,
                external_ids=external_ids,
                min_score=0.0,
                media_release_date=media_release_date_str,
                is_book=True,
                author=media_item.parent.title if media_item.parent else None,
            )
        else:
            # TV show episode
            return ReleaseMatcher.filter_matching_releases(
                releases=releases_data,
                media_title=show_context["show_title"] or media_item.title,
                media_year=media_year,
                season=show_context["season_number"],
                episode=show_context["episode_number"],
                external_ids=external_ids,
                min_score=0.0,
                media_release_date=media_release_date_str,
            )

    def _match_music_releases(
        self,
        media_item: MediaItem,
        releases_data: list[dict[str, Any]],
        media_year: int | None,
    ) -> list[tuple[dict[str, Any], Any]]:
        """Match music releases: Newznab via matcher, Spotify as exact."""
        artist_name = media_item.description or ""
        song_title = media_item.title
        album_title = None  # Already resolved at search time, not needed for match

        newznab_releases = [r for r in releases_data if r.get("source") != "spotify"]
        spotify_releases = [r for r in releases_data if r.get("source") == "spotify"]

        matching_releases = ReleaseMatcher.filter_matching_releases(
            releases=newznab_releases,
            media_title=media_item.title,
            media_year=media_year,
            artist=artist_name or None,
            album_title=album_title,
            song_title=song_title,
            min_score=0.0,
        )

        matching_releases.extend([
            (r, SimpleNamespace(match_type="spotify_exact", score=1.0))
            for r in spotify_releases
        ])

        return matching_releases

    async def _resolve_year(
        self, media_item: MediaItem, show_context: dict[str, Any]
    ) -> tuple[int | None, str | None]:
        """Resolve year and release date string for matching."""
        media_year = None
        media_release_date_str = None

        if media_item.release_date:
            media_year = media_item.release_date.year
            media_release_date_str = media_item.release_date.isoformat()

        if not media_year and show_context.get("season_number") is not None and media_item.parent_guid:
            try:
                season_result = await self.db.execute(
                    select(MediaItem.release_date).where(
                        MediaItem.guid == media_item.parent_guid
                    )
                )
                season_date = season_result.scalar_one_or_none()
                if season_date:
                    media_year = season_date.year
                    media_release_date_str = season_date.isoformat()
            except Exception as e:
                logger.debug("Failed to resolve year from season parent: %s", e)

        show = show_context.get("show")
        if not media_year and show and show.release_date:
            media_year = show.release_date.year
            media_release_date_str = show.release_date.isoformat()

        return media_year, media_release_date_str

    async def _persist_releases(
        self,
        media_item: MediaItem,
        matching_releases: list[tuple[dict[str, Any], Any]],
    ) -> int:
        """Deduplicate and persist releases and their links to the database."""
        release_count = 0
        seen_titles = {r.title for r in (media_item.releases or []) if r.title}

        # Get library plugin for metadata extraction
        library_plugin = None
        if media_item.media_type == MediaType.MOVIES:
            library_plugin = get_plugin_instance("MOVIES")
        elif media_item.media_type == MediaType.SHOWS:
            library_plugin = get_plugin_instance("SHOWS")
        elif media_item.media_type == MediaType.GAMES:
            library_plugin = get_plugin_instance("GAMES")

        for release_data, match_result in matching_releases:
            release_title = release_data.get("title")

            # Skip duplicates
            if release_title in seen_titles:
                continue
            seen_titles.add(release_title)

            # Build enriched metadata
            release_metadata = await self._enrich_metadata(
                release_title, match_result, release_data, library_plugin
            )

            # Parse publish_date
            parsed_publish_date = self._parse_publish_date(release_data.get("publish_date"))

            # Create release
            release = MediaRelease(
                guid=uuid.uuid4(),
                media_item_guid=media_item.guid,
                indexer_guid=release_data.get("indexer_guid"),
                title=release_title,
                size=release_data.get("size"),
                quality=release_data.get("quality"),
                score=0,
                publish_date=parsed_publish_date,
                release_metadata=release_metadata,
            )
            self.db.add(release)
            await self.db.flush()

            # Create release links
            self._create_release_links(release, release_data)

            release_count += 1

        await self.db.commit()
        return release_count

    async def _enrich_metadata(
        self,
        release_title: str | None,
        match_result: Any,
        release_data: dict[str, Any],
        library_plugin: Any,
    ) -> dict[str, Any]:
        """Build enriched metadata from library plugin, match info, and category hints."""
        release_metadata: dict[str, Any] = {}

        # Extract release metadata via library plugin
        if library_plugin and release_title:
            try:
                release_metadata = (
                    await library_plugin.extract_release_metadata(release_title)
                ) or {}
                logger.debug(
                    "Extracted metadata for %s: %s",
                    release_title,
                    release_metadata,
                )
            except Exception as e:
                logger.warning("Failed to extract metadata for %s: %s", release_title, e)

        # Add match info
        release_metadata["match_type"] = match_result.match_type
        release_metadata["match_score"] = match_result.score

        # Apply category-level language/resolution hints as fallbacks
        if release_title:
            self._apply_category_hints(release_title, release_data, release_metadata)

        return release_metadata

    def _apply_category_hints(
        self,
        release_title: str,
        release_data: dict[str, Any],
        release_metadata: dict[str, Any],
    ) -> None:
        """Apply category-level language and resolution hints when parser finds nothing."""
        from pyrate.parsers.release_parser import ReleaseParser

        lang_hints: list[str] = release_data.get("_category_lang_hints", [])
        if lang_hints and not ReleaseParser.LANGUAGE_PATTERN.search(release_title):
            release_metadata["languages"] = lang_hints
            release_metadata["languages_from_category"] = True
            logger.debug(
                "Applied category language hint %s to '%s'",
                lang_hints,
                release_title,
            )

        res_hints: list[str] = release_data.get("_category_res_hints", [])
        if res_hints and not release_metadata.get("resolution"):
            if len(res_hints) == 1:
                release_metadata["resolution"] = res_hints[0]
                release_metadata["quality"] = res_hints[0]
                release_metadata["resolution_from_category"] = True
                logger.debug(
                    "Applied category resolution hint %s to '%s'",
                    res_hints[0],
                    release_title,
                )

        # Final fallback: no resolution from parser or category -> assume SD
        if not release_metadata.get("resolution"):
            release_metadata["resolution"] = "480p"
            release_metadata["quality"] = "480p"
            release_metadata["resolution_assumed_sd"] = True

    @staticmethod
    def _parse_publish_date(raw_pub_date: Any) -> datetime | None:
        """Parse a publish_date value into a datetime."""
        if not raw_pub_date:
            return None
        if isinstance(raw_pub_date, str):
            try:
                from email.utils import parsedate_to_datetime

                return parsedate_to_datetime(raw_pub_date)
            except (ValueError, TypeError):
                try:
                    return datetime.fromisoformat(
                        raw_pub_date.replace("Z", "+00:00")
                    )
                except (ValueError, TypeError):
                    return None
        return raw_pub_date

    def _create_release_links(
        self, release: MediaRelease, release_data: dict[str, Any]
    ) -> None:
        """Create MediaReleaseLink objects for a release."""
        links_to_add: list[Any] = []

        if "links" in release_data:
            links_to_add = release_data["links"]
        elif "link" in release_data:
            default_link_type = "nzb"
            if release_data.get("source") == "spotify":
                default_link_type = "spotify"
            links_to_add = [{"link": release_data["link"], "link_type": default_link_type}]

        for link_data in links_to_add:
            if isinstance(link_data, dict):
                link_url = link_data.get("link")
                link_type = link_data.get("link_type", "nzb")
            else:
                link_url = link_data
                link_type = "nzb"

            if link_url:
                link = MediaReleaseLink(
                    guid=uuid.uuid4(),
                    media_release_guid=release.guid,
                    link=link_url,
                    link_type=link_type,
                )
                self.db.add(link)

    async def _publish_releases_updated(
        self, media_item: MediaItem, release_count: int, total_found: int
    ) -> None:
        """Publish WebSocket event for real-time UI updates."""
        try:
            from pyrate.services.redis_event import get_redis_event_service

            redis_service = get_redis_event_service()
            await redis_service.publish_media_item_updated(
                media_item_id=media_item.guid,
                update_type="releases_updated",
                data={
                    "releases_count": release_count,
                    "total_found": total_found,
                    "message": f"Found {release_count} new releases",
                },
            )
            logger.debug("Published releases_updated event for %s", media_item.guid)
        except Exception as e:
            logger.warning("Failed to publish WebSocket event: %s", e)
