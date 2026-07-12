import asyncio
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from pyrate.indexers.newznab import Newznab
from pyrate.indexers.torznab import Torznab
from pyrate.metadata.spotify import Spotify
from pyrate.models.indexer import Indexer, IndexerCategory
from pyrate.services.indexer_config import (
    IndexerService as IndexerConfigService,
)
from pyrate.services.observability import observe_indexer_search

logger = logging.getLogger(__name__)


class IndexerService:
    def __init__(self, db: AsyncSession, release_service=None):
        self.db = db
        self.indexer_config_service = IndexerConfigService(db)
        self.release_service = release_service
        self._indexer_cache = {}

    async def get_active_indexers(self) -> list[Indexer]:
        """Get all enabled indexers from the database"""
        result = await self.db.execute(
            select(Indexer)
            .options(selectinload(Indexer.categories))
            .where(Indexer.enabled.is_(True))
        )
        return result.scalars().all()

    async def get_indexers_by_category(self, category_type: str) -> list[Indexer]:
        """Get enabled indexers that support a category type (movie/show/game)"""
        result = await self.db.execute(
            select(Indexer)
            .options(selectinload(Indexer.categories))
            .join(Indexer.categories)
            .where(Indexer.enabled.is_(True))
            .where(IndexerCategory.category_type == category_type)
        )
        return result.scalars().unique().all()

    async def get_rss_indexers(self) -> list[Indexer]:
        """Enabled indexers opted into the periodic RSS poll, by priority."""
        result = await self.db.execute(
            select(Indexer)
            .options(selectinload(Indexer.categories))
            .where(Indexer.enabled.is_(True))
            .where(Indexer.rss_enabled.is_(True))
            .where(Indexer.supports_rss.is_(True))
            .order_by(Indexer.priority.asc())
        )
        return result.scalars().all()

    async def _fetch_recent_single(
        self, indexer: Indexer, limit: int
    ) -> list[dict[str, Any]]:
        indexer_type = (indexer.type or "newznab").lower().strip() or "newznab"
        with observe_indexer_search(indexer_type, "rss") as result_count:
            client = self._create_indexer_client(indexer)
            try:
                items = await client.fetch_recent(limit=limit)
            finally:
                await client.close()
            result_count[0] = len(items)
            return items

    async def fetch_recent_releases(
        self,
        indexers: list[Indexer] | None = None,
        *,
        per_indexer_limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Fan-out latest-feed fetch across RSS-enabled indexers, deduped
        by GUID then (title, size). Mirrors _search_across_indexers."""
        if indexers is None:
            indexers = await self.get_rss_indexers()
        if not indexers:
            return []

        results = await asyncio.gather(
            *[self._fetch_recent_single(ix, per_indexer_limit) for ix in indexers],
            return_exceptions=True,
        )
        merged: list[dict[str, Any]] = []
        for i, res in enumerate(results):
            if isinstance(res, Exception):
                logger.error(
                    "RSS fetch failed for indexer %s: %s",
                    indexers[i].label, res,
                )
                continue
            if res:
                merged.extend(res)

        # Dedup by GUID first (RSS items carry a stable guid), then fall
        # back to the existing (title, size) dedup for items without one.
        seen_guids: set[str] = set()
        guid_deduped: list[dict[str, Any]] = []
        for r in merged:
            g = str(r.get("guid") or "").strip()
            if g:
                if g in seen_guids:
                    continue
                seen_guids.add(g)
            guid_deduped.append(r)
        return self.deduplicate_releases(guid_deduped)

    def _get_category_ids_for_type(
        self, indexer: Indexer, category_type: str
    ) -> str | None:
        """Build a comma-separated list of newznab category IDs for the given content type."""
        ids = [
            str(cat.newznab_category_id)
            for cat in indexer.categories
            if cat.category_type == category_type
            and cat.newznab_category_id is not None
        ]
        return ",".join(ids) if ids else None

    def _get_language_hints_for_type(
        self, indexer: Indexer, category_type: str
    ) -> list[str]:
        """Collect all language hints from configured categories for the given content type."""
        hints: list[str] = []
        for cat in indexer.categories:
            if cat.category_type == category_type and cat.language:
                for lang in cat.language:
                    if lang not in hints:
                        hints.append(lang)
        return hints

    def _get_resolution_hints_for_type(
        self, indexer: Indexer, category_type: str
    ) -> list[str]:
        """Collect all resolution hints from configured categories for the given content type."""
        hints: list[str] = []
        for cat in indexer.categories:
            if cat.category_type == category_type and cat.resolution:
                for res in cat.resolution:
                    if res not in hints:
                        hints.append(res)
        return hints

    def _create_indexer_client(self, indexer: Indexer):
        """Create an indexer client instance based on indexer type"""
        indexer_type = indexer.type.lower().strip()

        # Check if host already contains protocol
        if indexer.host.startswith(("http://", "https://")):
            base_url = indexer.host
        else:
            protocol = "https" if indexer.ssl else "http"
            base_url = f"{protocol}://{indexer.host}"

        # Handle common variations and fix data issues
        if indexer_type in ["newznab", "string", ""]:
            # Default to newznab for empty or generic types
            return Newznab(
                base_url=base_url,
                api_key=indexer.api_key,
                id=str(indexer.guid),
                verify_ssl=indexer.verify_ssl,
            )
        elif indexer_type == "torznab":
            # Torznab for torrent indexers
            return Torznab(
                base_url=base_url,
                api_key=indexer.api_key,
                id=str(indexer.guid),
                verify_ssl=indexer.verify_ssl,
            )
        else:
            raise ValueError(f"Unsupported indexer type: {indexer.type}")

    async def search_movies(
        self,
        query: str | None = None,
        imdb_id: str | None = None,
        categories: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search for movies across all configured movie indexers.

        Uses a tiered search strategy (like Radarr):
        - Tier 0: ID-based search (imdbid only, no query text)
        - Tier 1: Title-based search (query text only, no ID)
        Results are deduplicated across tiers.
        """
        indexers = await self.get_indexers_by_category("movie")
        if not indexers:
            indexers = await self.get_active_indexers()

        results = []

        # Tier 0: ID-based search (preferred — more precise)
        if imdb_id:
            results = await self._search_across_indexers(
                indexers, "movie", imdb_id=imdb_id, categories=categories
            )

        # Tier 1: Title-based fallback (if ID search returned nothing)
        if not results and query:
            results = await self._search_across_indexers(
                indexers, "movie", query=query, categories=categories
            )

        return self.deduplicate_releases(results)

    async def search_shows(
        self,
        query: str | None = None,
        tvdb_id: str | None = None,
        imdb_id: str | None = None,
        season: str | None = None,
        episode: str | None = None,
        categories: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search for TV shows across all configured show indexers.

        Uses a tiered search strategy (like Sonarr):
        - Tier 0: ID-based search (tvdbid/imdbid only, no query text)
        - Tier 1: Title-based search (query text only, no IDs)
        Results are deduplicated across tiers.
        """
        indexers = await self.get_indexers_by_category("show")
        if not indexers:
            indexers = await self.get_active_indexers()

        results = []

        # Tier 0: ID-based search (preferred — more precise)
        if tvdb_id or imdb_id:
            results = await self._search_across_indexers(
                indexers,
                "show",
                tvdb_id=tvdb_id,
                imdb_id=imdb_id,
                season=season,
                episode=episode,
                categories=categories,
            )

        # Tier 1: Title-based fallback (if ID search returned nothing)
        if not results and query:
            results = await self._search_across_indexers(
                indexers,
                "show",
                query=query,
                season=season,
                episode=episode,
                categories=categories,
            )

        return self.deduplicate_releases(results)

    async def search_games(
        self, query: str | None = None, categories: str | None = None
    ) -> list[dict[str, Any]]:
        """Search for games across all configured game indexers"""
        indexers = await self.get_indexers_by_category("game")
        if not indexers:
            # Fallback to all indexers if no game-specific ones found
            indexers = await self.get_active_indexers()

        return await self._search_across_indexers(
            indexers, "game", query=query, categories=categories
        )

    async def search_music_releases(
        self,
        query: str | None = None,
        artist: str | None = None,
        album: str | None = None,
        categories: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search for music releases across Newznab/Torznab indexers.

        Uses tiered strategy like movies/shows:
        - Tier 0: artist + album params (t=music)
        - Tier 1: combined text query fallback
        """
        indexers = await self.get_indexers_by_category("music")
        if not indexers:
            return []

        results = []

        # Tier 0: Structured search with artist + album
        if artist:
            results = await self._search_across_indexers(
                indexers, "music",
                artist=artist, album=album, categories=categories,
            )

        # Tier 1: Text query fallback
        if not results and query:
            results = await self._search_across_indexers(
                indexers, "music",
                query=query, categories=categories,
            )

        return self.deduplicate_releases(results)

    async def search_books(
        self,
        query: str | None = None,
        author: str | None = None,
        title: str | None = None,
        categories: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search for book/audiobook releases across Newznab/Torznab indexers.

        Categories: 7010=ebooks, 3030=audiobooks, 7020=comics.
        """
        indexers = await self.get_indexers_by_category("book")
        if not indexers:
            # Fallback to all indexers
            indexers = await self.get_active_indexers()
        if not indexers:
            return []

        results = []

        # Tier 0: Structured search with author + title
        if author or title:
            results = await self._search_across_indexers(
                indexers, "book",
                author=author, title=title, categories=categories,
            )

        # Tier 1: Text query fallback
        if not results and query:
            results = await self._search_across_indexers(
                indexers, "book",
                query=query, categories=categories,
            )

        return self.deduplicate_releases(results)

    async def search_music(
        self,
        query: str | None = None,
        spotify_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search for music using the Spotify indexer plugin (for spotdl downloads).

        Unlike movie/show indexers which are user-configured DB entries,
        the Spotify indexer is a built-in plugin that uses Spotify API
        credentials from system settings.
        """
        from pyrate.services.settings import SettingsService

        settings_service = SettingsService(self.db)
        client_id, client_secret = await settings_service.get_spotify_credentials()
        if not client_id or not client_secret:
            logger.warning("Spotify credentials not configured, cannot search music")
            return []

        spotify = Spotify(client_id=client_id, client_secret=client_secret)
        try:
            return await spotify.search_music(
                q=query, spotify_id=spotify_id
            )
        except Exception as e:
            logger.error("Spotify music search failed: %s", e)
            return []
        finally:
            await spotify.close()

    async def search_across_all_indexers(
        self, content_type: str, **search_params
    ) -> list[dict[str, Any]]:
        """Search across all indexers for any content type"""
        indexers = await self.get_active_indexers()
        return await self._search_across_indexers(
            indexers, content_type, **search_params
        )

    async def _search_across_indexers(
        self, indexers: list[Indexer], content_type: str, **search_params
    ) -> list[dict[str, Any]]:
        """Internal method to search across a list of indexers"""
        if not indexers:
            logger.warning("No indexers available for %s search", content_type)
            return []

        tasks = []
        for indexer in indexers:
            # Inject per-indexer category IDs (override caller-supplied categories)
            params = dict(search_params)
            cat_ids = self._get_category_ids_for_type(indexer, content_type)
            if cat_ids:
                params["categories"] = cat_ids
            # Collect language/resolution hints from configured categories
            lang_hints = self._get_language_hints_for_type(indexer, content_type)
            res_hints = self._get_resolution_hints_for_type(indexer, content_type)
            task = self._search_single_indexer(
                indexer,
                content_type,
                _category_lang_hints=lang_hints or None,
                _category_res_hints=res_hints or None,
                **params,
            )
            tasks.append(task)

        # Execute all searches concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Combine results and filter out exceptions
        all_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error("Search failed for indexer %s: %s", indexers[i].label, result)
                continue
            if result:
                all_results.extend(result)

        return all_results

    async def _search_single_indexer(
        self,
        indexer: Indexer,
        content_type: str,
        _category_lang_hints: list[str] | None = None,
        _category_res_hints: list[str] | None = None,
        **search_params,
    ) -> list[dict[str, Any]]:
        """Search a single indexer for content"""
        indexer_type = (indexer.type or "unknown").lower().strip()
        try:
            with observe_indexer_search(indexer_type, content_type) as result_count:
                client = self._create_indexer_client(indexer)

                if content_type == "movie":
                    results = await client.search_movie(
                        q=search_params.get("query"),
                        imdb_id=search_params.get("imdb_id"),
                        categories=search_params.get("categories"),
                    )
                elif content_type == "show":
                    results = await client.search_show(
                        q=search_params.get("query"),
                        tvdb_id=search_params.get("tvdb_id"),
                        imdb_id=search_params.get("imdb_id"),
                        season=search_params.get("season"),
                        ep=search_params.get("episode"),
                        categories=search_params.get("categories"),
                    )
                elif content_type == "game":
                    results = await client.search_game(
                        q=search_params.get("query"),
                        categories=search_params.get("categories"),
                    )
                elif content_type == "music":
                    results = await client.search_music(
                        q=search_params.get("query"),
                        artist=search_params.get("artist"),
                        album=search_params.get("album"),
                        categories=search_params.get("categories"),
                    )
                elif content_type == "book":
                    results = await client.search_book(
                        q=search_params.get("query"),
                        author=search_params.get("author"),
                        title=search_params.get("title"),
                        categories=search_params.get("categories"),
                    )
                else:
                    raise ValueError(f"Unsupported content type: {content_type}")

                # Annotate results with category-level language/resolution hints.
                # These are used as fallbacks when the release title contains no
                # explicit language or resolution tags.
                if _category_lang_hints or _category_res_hints:
                    for r in results:
                        if _category_lang_hints:
                            r["_category_lang_hints"] = _category_lang_hints
                        if _category_res_hints:
                            r["_category_res_hints"] = _category_res_hints

                result_count[0] = len(results or [])
                return results

        except Exception as e:
            logger.error("Error searching indexer %s (%s): %s", indexer.label, indexer.host, e)
            return []

    async def process_and_score_releases(
        self, raw_results: list[dict[str, Any]], content_type: str = "movie"
    ) -> list[tuple[dict[str, Any], float]]:
        """Process raw indexer results through the release service for scoring"""
        scored_releases = []

        for result in raw_results:
            try:
                score = await self.release_service.score_release(result, content_type)
                scored_releases.append((result, score))
            except Exception as e:
                logger.error("Error scoring release %s: %s", result.get('title', 'Unknown'), e)
                # Include with score 0 if scoring fails
                scored_releases.append((result, 0.0))

        # Sort by score descending
        scored_releases.sort(key=lambda x: x[1], reverse=True)
        return scored_releases

    def deduplicate_releases(
        self, releases: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Remove duplicate releases based on title and size"""
        seen = set()
        deduplicated = []

        for release in releases:
            # Create a deduplication key based on title and size
            title = release.get("title", "").lower().strip()
            size = release.get("size", 0)

            dedup_key = (title, size)
            if dedup_key not in seen:
                seen.add(dedup_key)
                deduplicated.append(release)
            else:
                logger.debug("Skipping duplicate release: %s", title)

        return deduplicated

    async def search_and_process(
        self, content_type: str, deduplicate: bool = True, **search_params
    ) -> list[tuple[dict[str, Any], float]]:
        """Complete search and processing pipeline"""
        # Search across indexers
        if content_type == "movie":
            raw_results = await self.search_movies(**search_params)
        elif content_type == "show":
            raw_results = await self.search_shows(**search_params)
        elif content_type == "game":
            raw_results = await self.search_games(**search_params)
        else:
            raw_results = await self.search_across_all_indexers(
                content_type, **search_params
            )

        # Deduplicate if requested
        if deduplicate:
            raw_results = self.deduplicate_releases(raw_results)

        # Process and score
        return await self.process_and_score_releases(raw_results, content_type)
