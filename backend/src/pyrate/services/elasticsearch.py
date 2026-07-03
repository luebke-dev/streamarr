"""Elasticsearch service for full-text search of movies and shows."""

import logging
import time
from typing import Any
from uuid import UUID

from elasticsearch import AsyncElasticsearch
from elasticsearch.exceptions import ConnectionError, NotFoundError
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_object_session
from sqlalchemy.orm import selectinload

from ..config import settings
from ..models.media import MediaItem
from ..schemas.search import SearchRequest, SearchType

logger = logging.getLogger(__name__)

# Max items per bulk request. Keeps memory and request size predictable when a
# caller passes a "full library" list (tens of thousands of rows).
_BULK_CHUNK_SIZE = 500


def _safe_related(obj: Any, attr: str) -> list:
    """Return a relationship collection, or ``[]`` when it is not loaded.

    Accessing an unloaded lazy relationship raises in an async context, and
    test doubles may not carry the attribute at all — either way we treat it
    as empty rather than letting a single item blow up a whole bulk request.
    """
    try:
        value = getattr(obj, attr)
    except Exception:
        return []
    if value is None:
        return []
    try:
        return list(value)
    except TypeError:
        return []


def _genres_doc(item: MediaItem) -> list[dict[str, Any]]:
    """Build the nested ``genres`` sub-document (drives the genre facet filter)."""
    return [{"id": g.id, "name": g.name} for g in _safe_related(item, "genres")]


def _external_ids_doc(item: MediaItem) -> dict[str, Any]:
    """Build the ``external_ids`` sub-document (drives TMDB/IMDb ID lookups)."""
    ids: dict[str, Any] = {}
    for ext in _safe_related(item, "external_ids"):
        provider = getattr(ext, "provider", None)
        if provider == "tmdb":
            ids["tmdb_id"] = ext.external_id
        elif provider == "imdb":
            ids["imdb_id"] = ext.external_id
    return ids


async def _ensure_facets_loaded(items: list[MediaItem]) -> None:
    """Eager-load ``genres`` + ``external_ids`` onto ORM items sharing a session.

    The full-reindex path hands us items fetched without these relationships.
    Loading them here — one selectin round-trip per chunk — is what makes genre
    filters and ID lookups work after a bulk reindex. No-op for detached
    objects or non-ORM test doubles.
    """
    try:
        pending: list[MediaItem] = []
        for item in items:
            try:
                unloaded = sa_inspect(item).unloaded
            except Exception:
                # Not an ORM instance (e.g. a MagicMock in tests).
                return
            if "genres" in unloaded or "external_ids" in unloaded:
                pending.append(item)
        if not pending:
            return
        session = async_object_session(pending[0])
        if session is None:
            return
        guids = [item.guid for item in pending]
        # Re-querying the same session with selectinload populates the
        # identity-mapped instances in place, so the objects the caller holds
        # gain their genres/external_ids collections.
        await session.execute(
            select(MediaItem)
            .where(MediaItem.guid.in_(guids))
            .options(
                selectinload(MediaItem.genres),
                selectinload(MediaItem.external_ids),
            )
        )
    except Exception as exc:
        logger.debug("Facet preload skipped: %s", exc)


def _movie_doc(movie: MediaItem) -> dict[str, Any]:
    """Build the Elasticsearch document for a movie (shared by single + bulk)."""
    return {
        "id": str(movie.guid),
        "title": movie.title,
        "original_title": movie.original_title,
        "description": movie.description,
        "tagline": movie.tagline,
        "release_date": movie.release_date.isoformat()
        if movie.release_date
        else None,
        "poster_path": movie.poster_path,
        "backdrop_path": movie.backdrop_path,
        "availability_status": movie.availability_status,
        "genres": _genres_doc(movie),
        "external_ids": _external_ids_doc(movie),
        "created_at": movie.created_at.isoformat() if movie.created_at else None,
        "updated_at": movie.updated_at.isoformat() if movie.updated_at else None,
    }


def _show_doc(show: MediaItem) -> dict[str, Any]:
    """Build the Elasticsearch document for a show (shared by single + bulk).

    The unified ``MediaItem`` stores the air date in ``release_date``; it is
    mapped onto the ``first_air_date`` field the show index/query expect.
    """
    return {
        "id": str(show.guid),
        "title": show.title,
        "original_title": show.original_title,
        "description": show.description,
        "tagline": show.tagline,
        "first_air_date": show.release_date.isoformat()
        if show.release_date
        else None,
        "poster_path": show.poster_path,
        "backdrop_path": show.backdrop_path,
        "genres": _genres_doc(show),
        "external_ids": _external_ids_doc(show),
        "created_at": show.created_at.isoformat() if show.created_at else None,
        "updated_at": show.updated_at.isoformat() if show.updated_at else None,
    }


class ElasticsearchService:
    """Service wrapping Elasticsearch operations."""

    def __init__(self):
        self.client: AsyncElasticsearch | None = None
        self.index_prefix = settings.elasticsearch.index_prefix

    async def initialize(self) -> None:
        """Initialise the Elasticsearch connection.

        On any ping failure (transport error or non-2xx response — for
        example a 400 from a version-mismatched server) the client is set
        to ``None``. Every search call site already short-circuits when
        ``self.client is None`` and falls back to the local DB; leaving a
        zombie client behind otherwise lets every search 500 silently.
        """
        client: AsyncElasticsearch | None = None
        try:
            client = AsyncElasticsearch(
                hosts=[
                    f"http://{settings.elasticsearch.host}:{settings.elasticsearch.port}"
                ],
                verify_certs=settings.elasticsearch.verify_certs,
                request_timeout=settings.elasticsearch.timeout,
                max_retries=settings.elasticsearch.max_retries,
            )

            ping_ok = False
            try:
                ping_ok = await client.ping()
            except Exception as ping_err:
                logger.error("Elasticsearch ping raised: %s", ping_err)

            if ping_ok:
                self.client = client
                logger.info("Elasticsearch connection established")
                await self._create_indices()
            else:
                logger.error(
                    "Elasticsearch ping failed; disabling client. "
                    "Search will fall back to local DB."
                )
                try:
                    await client.close()
                except Exception:
                    pass
                self.client = None

        except ConnectionError as e:
            logger.error("Elasticsearch connection error: %s", e)
            self.client = None
            if client is not None:
                try:
                    await client.close()
                except Exception:
                    pass

    async def close(self) -> None:
        """Close the Elasticsearch connection."""
        if self.client:
            await self.client.close()

    async def _create_indices(self) -> None:
        """Create the Elasticsearch indices for movies and shows."""
        movie_mapping = {
            "mappings": {
                "properties": {
                    "id": {"type": "keyword"},
                    "title": {
                        "type": "text",
                        "analyzer": "standard",
                        "fields": {
                            "keyword": {"type": "keyword"},
                            "suggest": {"type": "completion"},
                        },
                    },
                    "original_title": {
                        "type": "text",
                        "analyzer": "standard",
                        "fields": {"keyword": {"type": "keyword"}},
                    },
                    "description": {"type": "text", "analyzer": "standard"},
                    "tagline": {"type": "text", "analyzer": "standard"},
                    "release_date": {"type": "date"},
                    "runtime": {"type": "integer"},
                    "rating": {"type": "float"},
                    "vote_count": {"type": "integer"},
                    "popularity": {"type": "float"},
                    "genres": {
                        "type": "nested",
                        "properties": {
                            "id": {"type": "integer"},
                            "name": {"type": "keyword"},
                        },
                    },
                    "external_ids": {
                        "type": "object",
                        "properties": {
                            "tmdb_id": {"type": "integer"},
                            "imdb_id": {"type": "keyword"},
                        },
                    },
                    "created_at": {"type": "date"},
                    "updated_at": {"type": "date"},
                }
            }
        }

        show_mapping = {
            "mappings": {
                "properties": {
                    "id": {"type": "keyword"},
                    "title": {
                        "type": "text",
                        "analyzer": "standard",
                        "fields": {
                            "keyword": {"type": "keyword"},
                            "suggest": {"type": "completion"},
                        },
                    },
                    "original_title": {
                        "type": "text",
                        "analyzer": "standard",
                        "fields": {"keyword": {"type": "keyword"}},
                    },
                    "description": {"type": "text", "analyzer": "standard"},
                    "tagline": {"type": "text", "analyzer": "standard"},
                    "first_air_date": {"type": "date"},
                    "last_air_date": {"type": "date"},
                    "status": {"type": "keyword"},
                    "rating": {"type": "float"},
                    "vote_count": {"type": "integer"},
                    "popularity": {"type": "float"},
                    "number_of_seasons": {"type": "integer"},
                    "number_of_episodes": {"type": "integer"},
                    "genres": {
                        "type": "nested",
                        "properties": {
                            "id": {"type": "integer"},
                            "name": {"type": "keyword"},
                        },
                    },
                    "external_ids": {
                        "type": "object",
                        "properties": {
                            "tmdb_id": {"type": "integer"},
                            "imdb_id": {"type": "keyword"},
                        },
                    },
                    "created_at": {"type": "date"},
                    "updated_at": {"type": "date"},
                }
            }
        }

        book_mapping = {
            "mappings": {
                "properties": {
                    "id": {"type": "keyword"},
                    "title": {
                        "type": "text",
                        "analyzer": "standard",
                        "fields": {
                            "keyword": {"type": "keyword"},
                            "suggest": {"type": "completion"},
                        },
                    },
                    "description": {"type": "text", "analyzer": "standard"},
                    "release_date": {"type": "date"},
                    "poster_path": {"type": "keyword"},
                    "genres": {
                        "type": "nested",
                        "properties": {
                            "id": {"type": "integer"},
                            "name": {"type": "keyword"},
                        },
                    },
                    "external_ids": {
                        "type": "object",
                        "properties": {
                            "openlibrary_id": {"type": "keyword"},
                        },
                    },
                    "created_at": {"type": "date"},
                    "updated_at": {"type": "date"},
                }
            }
        }

        # Indizes erstellen falls sie nicht existieren
        movie_index = f"{self.index_prefix}_movies"
        show_index = f"{self.index_prefix}_shows"
        book_index = f"{self.index_prefix}_books"

        try:
            if not await self.client.indices.exists(index=movie_index):
                await self.client.indices.create(index=movie_index, body=movie_mapping)
                logger.info("Movie-Index '%s' erstellt", movie_index)

            if not await self.client.indices.exists(index=show_index):
                await self.client.indices.create(index=show_index, body=show_mapping)
                logger.info("Show-Index '%s' erstellt", show_index)

            if not await self.client.indices.exists(index=book_index):
                await self.client.indices.create(index=book_index, body=book_mapping)
                logger.info("Book-Index '%s' erstellt", book_index)

        except Exception as e:
            logger.error("Fehler beim Erstellen der Indizes: %s", e)

    async def index_movie(self, movie: MediaItem) -> bool:
        """Index a single movie in Elasticsearch.

        Uses the shared ``_movie_doc`` builder so a single-item update and a
        bulk reindex always produce the same document (including real genres
        and external IDs).
        """
        if not self.client:
            return False

        try:
            index_name = f"{self.index_prefix}_movies"
            await self.client.index(
                index=index_name, id=str(movie.guid), body=_movie_doc(movie)
            )
            logger.debug("Film '%s' erfolgreich indexiert", movie.title)
            return True

        except Exception as e:
            logger.error("Fehler beim Indexieren des Films '%s': %s", movie.title, e)
            return False

    async def index_show(self, show: MediaItem) -> bool:
        """Index a single show in Elasticsearch.

        Uses the shared ``_show_doc`` builder so a single-item update and a
        bulk reindex always produce the same document.
        """
        if not self.client:
            return False

        try:
            index_name = f"{self.index_prefix}_shows"
            await self.client.index(
                index=index_name, id=str(show.guid), body=_show_doc(show)
            )
            logger.debug("Serie '%s' erfolgreich indexiert", show.title)
            return True

        except Exception as e:
            logger.error("Fehler beim Indexieren der Serie '%s': %s", show.title, e)
            return False

    async def index_media_item(self, item: MediaItem) -> bool:
        """Index a single media item into the index matching its media type.

        Only the media types that have an index (movies, shows, books) are
        handled; anything else (episodes, games, music, ...) is a no-op.
        """
        media_type = getattr(item.media_type, "value", str(item.media_type))
        if media_type == "MOVIES":
            return await self.index_movie(item)
        if media_type == "SHOWS":
            return await self.index_show(item)
        if media_type == "BOOKS":
            return await self.index_book(item)
        return False

    async def delete_media_item(self, item_guid: UUID, media_type: Any) -> bool:
        """Remove a single item from the index matching its media type."""
        media_type = getattr(media_type, "value", str(media_type))
        if media_type == "MOVIES":
            return await self.delete_movie(item_guid)
        if media_type == "SHOWS":
            return await self.delete_show(item_guid)
        if media_type == "BOOKS":
            if not self.client:
                return False
            try:
                await self.client.delete(
                    index=f"{self.index_prefix}_books", id=str(item_guid)
                )
                return True
            except NotFoundError:
                return True
            except Exception as e:
                logger.error("Failed to delete book '%s': %s", item_guid, e)
                return False
        return False

    async def index_book(self, book: MediaItem) -> bool:
        """Index a book in Elasticsearch."""
        if not self.client:
            return False

        try:
            genres = []
            if hasattr(book, 'genres') and book.genres:
                genres = [{"id": g.id, "name": g.name} for g in book.genres]

            external_ids = {}
            if hasattr(book, 'external_ids') and book.external_ids:
                for ext in book.external_ids:
                    if ext.provider == "openlibrary":
                        external_ids["openlibrary_id"] = ext.external_id

            doc = {
                "id": str(book.guid),
                "title": book.title,
                "description": book.description,
                "release_date": book.release_date.isoformat() if book.release_date else None,
                "poster_path": book.poster_path,
                "genres": genres,
                "external_ids": external_ids,
                "created_at": book.created_at.isoformat() if book.created_at else None,
                "updated_at": book.updated_at.isoformat() if book.updated_at else None,
            }

            index_name = f"{self.index_prefix}_books"
            await self.client.index(index=index_name, id=str(book.guid), body=doc)
            logger.debug("Book '%s' indexed successfully", book.title)
            return True

        except Exception as e:
            logger.error("Error indexing book '%s': %s", book.title, e)
            return False

    async def bulk_index_books(self, books: list[MediaItem]) -> dict[str, int]:
        """Bulk index books into Elasticsearch."""
        stats = {"indexed": 0, "errors": 0}
        if not self.client or not books:
            return stats

        try:
            index_name = f"{self.index_prefix}_books"
            actions = []
            for book in books:
                genres = []
                if hasattr(book, 'genres') and book.genres:
                    genres = [{"id": g.id, "name": g.name} for g in book.genres]

                external_ids = {}
                if hasattr(book, 'external_ids') and book.external_ids:
                    for ext in book.external_ids:
                        if ext.provider == "openlibrary":
                            external_ids["openlibrary_id"] = ext.external_id

                doc = {
                    "id": str(book.guid),
                    "title": book.title,
                    "description": book.description,
                    "release_date": book.release_date.isoformat() if book.release_date else None,
                    "poster_path": book.poster_path,
                    "genres": genres,
                    "external_ids": external_ids,
                    "created_at": book.created_at.isoformat() if book.created_at else None,
                    "updated_at": book.updated_at.isoformat() if book.updated_at else None,
                }
                actions.append({"_index": index_name, "_id": str(book.guid), "_source": doc})

            if actions:
                from elasticsearch.helpers import async_bulk
                success, errors = await async_bulk(self.client, actions)
                stats["indexed"] = success
                stats["errors"] = len(errors) if isinstance(errors, list) else 0
                logger.info("Bulk indexed %d books (%d errors)", success, stats["errors"])

        except Exception as e:
            logger.error("Error bulk indexing books: %s", e)

        return stats

    async def search_movies(self, search_request: SearchRequest) -> dict[str, Any]:
        """Sucht nach Filmen mit Full-Text-Search."""
        start_time = time.time()

        if not self.client:
            return {
                "hits": [],
                "total": 0,
                "page": search_request.page,
                "per_page": search_request.per_page,
                "total_pages": 0,
                "query": search_request.query,
                "search_type": search_request.search_type,
                "took": 0,
            }

        try:
            index_name = f"{self.index_prefix}_movies"

            # Pagination berechnen
            offset = (search_request.page - 1) * search_request.per_page

            # Base query for multi-field search with boosting.
            search_query = {
                "bool": {
                    "should": [
                        {
                            "match": {
                                "title": {"query": search_request.query, "boost": 3.0}
                            }
                        },
                        {
                            "match": {
                                "original_title": {
                                    "query": search_request.query,
                                    "boost": 2.0,
                                }
                            }
                        },
                        {
                            "match": {
                                "description": {
                                    "query": search_request.query,
                                    "boost": 1.0,
                                }
                            }
                        },
                        {
                            "match": {
                                "tagline": {"query": search_request.query, "boost": 1.5}
                            }
                        },
                    ],
                    "minimum_should_match": 1,
                }
            }

            # Add fuzzy search when enabled.
            if search_request.fuzzy:
                search_query["bool"]["should"].extend(
                    [
                        {
                            "fuzzy": {
                                "title": {
                                    "value": search_request.query,
                                    "fuzziness": "AUTO",
                                    "boost": 0.5,
                                }
                            }
                        },
                        {
                            "fuzzy": {
                                "original_title": {
                                    "value": search_request.query,
                                    "fuzziness": "AUTO",
                                    "boost": 0.3,
                                }
                            }
                        },
                    ]
                )

            # Add filters.
            filter_clauses = []

            if search_request.genres:
                filter_clauses.append(
                    {
                        "nested": {
                            "path": "genres",
                            "query": {"terms": {"genres.name": search_request.genres}},
                        }
                    }
                )

            if search_request.year_from or search_request.year_to:
                date_range = {}
                if search_request.year_from:
                    date_range["gte"] = f"{search_request.year_from}-01-01"
                if search_request.year_to:
                    date_range["lte"] = f"{search_request.year_to}-12-31"

                filter_clauses.append({"range": {"release_date": date_range}})

            if filter_clauses:
                search_query["bool"]["filter"] = filter_clauses

            # Sortierung bestimmen - use _score as default since popularity may not exist
            sort_field = "_score"
            sort_order = "desc"

            if search_request.sort_by:
                if search_request.sort_by == "title":
                    sort_field = "title.keyword"
                elif search_request.sort_by == "rating":
                    sort_field = "rating"
                elif search_request.sort_by == "release_date":
                    sort_field = "release_date"
                elif search_request.sort_by == "popularity":
                    sort_field = (
                        "_score"  # Fall back to score since popularity may not exist
                    )

            if search_request.sort_order:
                sort_order = search_request.sort_order

            # Build sort array - handle missing fields gracefully
            sort_array = [{"_score": {"order": "desc"}}]
            if sort_field != "_score":
                sort_array.append(
                    {sort_field: {"order": sort_order, "unmapped_type": "float"}}
                )
            sort_array.append(
                {"release_date": {"order": "desc", "unmapped_type": "date"}}
            )

            # Execute the Elasticsearch query.
            response = await self.client.search(
                index=index_name,
                body={
                    "query": search_query,
                    "from": offset,
                    "size": search_request.per_page,
                    "sort": sort_array,
                    "highlight": {
                        "fields": {
                            "title": {},
                            "original_title": {},
                            "description": {"fragment_size": 150},
                        }
                    },
                },
            )

            hits = []
            for hit in response["hits"]["hits"]:
                movie_data = hit["_source"]
                # Rename "id" field to "guid" for schema compatibility.
                if "id" in movie_data:
                    movie_data["guid"] = movie_data.pop("id")
                movie_data["score"] = hit["_score"]
                if "highlight" in hit:
                    movie_data["highlight"] = hit["highlight"]
                hits.append(movie_data)

            # Pagination berechnen
            total = response["hits"]["total"]["value"]
            total_pages = (
                total + search_request.per_page - 1
            ) // search_request.per_page

            # Timing berechnen
            took = int((time.time() - start_time) * 1000)  # in Millisekunden

            return {
                "hits": hits,
                "total": total,
                "page": search_request.page,
                "per_page": search_request.per_page,
                "total_pages": total_pages,
                "query": search_request.query,
                "search_type": search_request.search_type,
                "took": took,
            }

        except Exception as e:
            logger.error("Fehler bei der Film-Suche: %s", e)
            took = int((time.time() - start_time) * 1000)
            return {
                "hits": [],
                "total": 0,
                "page": search_request.page,
                "per_page": search_request.per_page,
                "total_pages": 0,
                "query": search_request.query,
                "search_type": search_request.search_type,
                "took": took,
            }

    async def search_shows(self, search_request: SearchRequest) -> dict[str, Any]:
        """Sucht nach Serien mit Full-Text-Search."""
        start_time = time.time()

        if not self.client:
            return {
                "hits": [],
                "total": 0,
                "page": search_request.page,
                "per_page": search_request.per_page,
                "total_pages": 0,
                "query": search_request.query,
                "search_type": search_request.search_type,
                "took": 0,
            }

        try:
            index_name = f"{self.index_prefix}_shows"

            # Pagination berechnen
            offset = (search_request.page - 1) * search_request.per_page

            # Base query for multi-field search with boosting.
            search_query = {
                "bool": {
                    "should": [
                        {
                            "match": {
                                "title": {"query": search_request.query, "boost": 3.0}
                            }
                        },
                        {
                            "match": {
                                "original_title": {
                                    "query": search_request.query,
                                    "boost": 2.0,
                                }
                            }
                        },
                        {
                            "match": {
                                "description": {
                                    "query": search_request.query,
                                    "boost": 1.0,
                                }
                            }
                        },
                        {
                            "match": {
                                "tagline": {"query": search_request.query, "boost": 1.5}
                            }
                        },
                    ],
                    "minimum_should_match": 1,
                }
            }

            # Add fuzzy search when enabled.
            if search_request.fuzzy:
                search_query["bool"]["should"].extend(
                    [
                        {
                            "fuzzy": {
                                "title": {
                                    "value": search_request.query,
                                    "fuzziness": "AUTO",
                                    "boost": 0.5,
                                }
                            }
                        },
                        {
                            "fuzzy": {
                                "original_title": {
                                    "value": search_request.query,
                                    "fuzziness": "AUTO",
                                    "boost": 0.3,
                                }
                            }
                        },
                    ]
                )

            # Add filters.
            filter_clauses = []

            if search_request.genres:
                filter_clauses.append(
                    {
                        "nested": {
                            "path": "genres",
                            "query": {"terms": {"genres.name": search_request.genres}},
                        }
                    }
                )

            if search_request.year_from or search_request.year_to:
                date_range = {}
                if search_request.year_from:
                    date_range["gte"] = f"{search_request.year_from}-01-01"
                if search_request.year_to:
                    date_range["lte"] = f"{search_request.year_to}-12-31"

                filter_clauses.append({"range": {"first_air_date": date_range}})

            if filter_clauses:
                search_query["bool"]["filter"] = filter_clauses

            # Sortierung bestimmen - use _score as default since popularity may not exist
            sort_field = "_score"
            sort_order = "desc"

            if search_request.sort_by:
                if search_request.sort_by == "title":
                    sort_field = "title.keyword"
                elif search_request.sort_by == "rating":
                    sort_field = "rating"
                elif search_request.sort_by == "release_date":
                    sort_field = "first_air_date"
                elif search_request.sort_by == "popularity":
                    sort_field = (
                        "_score"  # Fall back to score since popularity may not exist
                    )

            if search_request.sort_order:
                sort_order = search_request.sort_order

            # Build sort array - handle missing fields gracefully
            sort_array = [{"_score": {"order": "desc"}}]
            if sort_field != "_score":
                sort_array.append(
                    {sort_field: {"order": sort_order, "unmapped_type": "float"}}
                )
            sort_array.append(
                {"first_air_date": {"order": "desc", "unmapped_type": "date"}}
            )

            # Execute the Elasticsearch query.
            response = await self.client.search(
                index=index_name,
                body={
                    "query": search_query,
                    "from": offset,
                    "size": search_request.per_page,
                    "sort": sort_array,
                    "highlight": {
                        "fields": {
                            "title": {},
                            "original_title": {},
                            "description": {"fragment_size": 150},
                        }
                    },
                },
            )

            hits = []
            for hit in response["hits"]["hits"]:
                show_data = hit["_source"]
                # Rename "id" field to "guid" for schema compatibility.
                if "id" in show_data:
                    show_data["guid"] = show_data.pop("id")
                show_data["score"] = hit["_score"]
                if "highlight" in hit:
                    show_data["highlight"] = hit["highlight"]
                hits.append(show_data)

            # Pagination berechnen
            total = response["hits"]["total"]["value"]
            total_pages = (
                total + search_request.per_page - 1
            ) // search_request.per_page

            # Timing berechnen
            took = int((time.time() - start_time) * 1000)  # in Millisekunden

            return {
                "hits": hits,
                "total": total,
                "page": search_request.page,
                "per_page": search_request.per_page,
                "total_pages": total_pages,
                "query": search_request.query,
                "search_type": search_request.search_type,
                "took": took,
            }

        except Exception as e:
            logger.error("Fehler bei der Serien-Suche: %s", e)
            took = int((time.time() - start_time) * 1000)
            return {
                "hits": [],
                "total": 0,
                "page": search_request.page,
                "per_page": search_request.per_page,
                "total_pages": 0,
                "query": search_request.query,
                "search_type": search_request.search_type,
                "took": took,
            }

    async def delete_movie(self, movie_id: UUID) -> bool:
        """Delete a movie from the Elasticsearch index."""
        if not self.client:
            return False

        try:
            index_name = f"{self.index_prefix}_movies"
            await self.client.delete(index=index_name, id=str(movie_id))
            logger.debug("Movie with id '%s' deleted from index", movie_id)
            return True

        except NotFoundError:
            logger.warning("Movie with id '%s' not found in index", movie_id)
            return True
        except Exception as e:
            logger.error("Failed to delete movie '%s': %s", movie_id, e)
            return False

    async def delete_show(self, show_id: UUID) -> bool:
        """Delete a show from the Elasticsearch index."""
        if not self.client:
            return False

        try:
            index_name = f"{self.index_prefix}_shows"
            await self.client.delete(index=index_name, id=str(show_id))
            logger.debug("Show with id '%s' deleted from index", show_id)
            return True

        except NotFoundError:
            logger.warning("Show with id '%s' not found in index", show_id)
            return True
        except Exception as e:
            logger.error("Failed to delete show '%s': %s", show_id, e)
            return False

    async def bulk_index_movies(self, movies: list[MediaItem]) -> dict[str, int]:
        """Bulk-index movies in chunks so large lists don't exhaust memory."""
        if not self.client or not movies:
            return {"success": 0, "failed": 0}

        index_name = f"{self.index_prefix}_movies"
        success_count = 0
        failed_count = 0

        for chunk_start in range(0, len(movies), _BULK_CHUNK_SIZE):
            chunk = movies[chunk_start : chunk_start + _BULK_CHUNK_SIZE]
            try:
                # Load genres + external_ids so the reindexed docs carry real
                # facets (genre filter + ID lookups) instead of empty stubs.
                await _ensure_facets_loaded(chunk)
                actions: list[Any] = []
                for movie in chunk:
                    actions.append(
                        {"index": {"_index": index_name, "_id": str(movie.guid)}}
                    )
                    actions.append(_movie_doc(movie))

                response = await self.client.bulk(operations=actions)

                for item in response["items"]:
                    if "index" in item:
                        if item["index"]["status"] in [200, 201]:
                            success_count += 1
                        else:
                            failed_count += 1
                            logger.error("Bulk-Index Fehler: %s", item['index'])
            except Exception as e:
                logger.error(
                    "Fehler beim Bulk-Indexieren der Filme (chunk offset %d): %s",
                    chunk_start, e,
                )
                failed_count += len(chunk)

        logger.info(
            "Bulk-Indexierung Filme: %s erfolgreich, %s fehlgeschlagen",
            success_count, failed_count,
        )
        return {"success": success_count, "failed": failed_count}

    async def bulk_index_shows(self, shows: list[MediaItem]) -> dict[str, int]:
        """Indexiert mehrere Serien chunk-weise."""
        if not self.client or not shows:
            return {"success": 0, "failed": 0}

        index_name = f"{self.index_prefix}_shows"
        success_count = 0
        failed_count = 0

        for chunk_start in range(0, len(shows), _BULK_CHUNK_SIZE):
            chunk = shows[chunk_start : chunk_start + _BULK_CHUNK_SIZE]
            try:
                # Load genres + external_ids so the reindexed docs carry real
                # facets (genre filter + ID lookups) instead of empty stubs.
                await _ensure_facets_loaded(chunk)
                actions: list[Any] = []
                for show in chunk:
                    actions.append({"index": {"_index": index_name, "_id": str(show.guid)}})
                    actions.append(_show_doc(show))

                response = await self.client.bulk(operations=actions)

                for item in response["items"]:
                    if "index" in item:
                        if item["index"]["status"] in [200, 201]:
                            success_count += 1
                        else:
                            failed_count += 1
                            logger.error("Bulk-Index Fehler: %s", item['index'])
            except Exception as e:
                logger.error(
                    "Fehler beim Bulk-Indexieren der Serien (chunk offset %d): %s",
                    chunk_start, e,
                )
                failed_count += len(chunk)

        logger.info(
            "Bulk-Indexierung Serien: %s erfolgreich, %s fehlgeschlagen",
            success_count, failed_count,
        )
        return {"success": success_count, "failed": failed_count}

    async def search_all(self, search_request: SearchRequest) -> dict[str, Any]:
        """Unified search across all content (movies and shows)."""
        start_time = time.time()

        if not self.client:
            return {
                "hits": [],
                "total": 0,
                "page": search_request.page,
                "per_page": search_request.per_page,
                "total_pages": 0,
                "query": search_request.query,
                "search_type": search_request.search_type,
                "took": 0,
            }

        try:
            # Je nach search_type die entsprechenden Indizes bestimmen
            if search_request.search_type == SearchType.MOVIES:
                return await self.search_movies(search_request)
            elif search_request.search_type == SearchType.SHOWS:
                return await self.search_shows(search_request)
            elif search_request.search_type == SearchType.ALL:
                # Multi-index search across all indices.
                indices = [
                    f"{self.index_prefix}_movies",
                    f"{self.index_prefix}_shows",
                    f"{self.index_prefix}_books",
                ]
            else:
                # Fallback auf ALL
                indices = [
                    f"{self.index_prefix}_movies",
                    f"{self.index_prefix}_shows",
                    f"{self.index_prefix}_books",
                ]

            # Pagination berechnen
            offset = (search_request.page - 1) * search_request.per_page

            # Base query for multi-field search with boosting.
            search_query = {
                "bool": {
                    "should": [
                        {
                            "match": {
                                "title": {"query": search_request.query, "boost": 3.0}
                            }
                        },
                        {
                            "match": {
                                "original_title": {
                                    "query": search_request.query,
                                    "boost": 2.0,
                                }
                            }
                        },
                        {
                            "match": {
                                "description": {
                                    "query": search_request.query,
                                    "boost": 1.0,
                                }
                            }
                        },
                        {
                            "match": {
                                "tagline": {"query": search_request.query, "boost": 1.5}
                            }
                        },
                    ],
                    "minimum_should_match": 1,
                }
            }

            # Add fuzzy search when enabled.
            if search_request.fuzzy:
                search_query["bool"]["should"].extend(
                    [
                        {
                            "fuzzy": {
                                "title": {
                                    "value": search_request.query,
                                    "fuzziness": "AUTO",
                                    "boost": 0.5,
                                }
                            }
                        },
                        {
                            "fuzzy": {
                                "original_title": {
                                    "value": search_request.query,
                                    "fuzziness": "AUTO",
                                    "boost": 0.3,
                                }
                            }
                        },
                    ]
                )

            # Add filters.
            filter_clauses = []

            if search_request.genres:
                filter_clauses.append(
                    {
                        "nested": {
                            "path": "genres",
                            "query": {"terms": {"genres.name": search_request.genres}},
                        }
                    }
                )

            if search_request.year_from or search_request.year_to:
                date_range = {}
                if search_request.year_from:
                    date_range["gte"] = f"{search_request.year_from}-01-01"
                if search_request.year_to:
                    date_range["lte"] = f"{search_request.year_to}-12-31"

                # For multi-index search, consider both date fields.
                date_filter = {
                    "bool": {
                        "should": [
                            {"range": {"release_date": date_range}},
                            {"range": {"first_air_date": date_range}},
                        ]
                    }
                }
                filter_clauses.append(date_filter)

            if filter_clauses:
                search_query["bool"]["filter"] = filter_clauses

            # Sortierung bestimmen - use _score as default since popularity may not exist
            sort_field = "_score"
            sort_order = "desc"

            if search_request.sort_by:
                if search_request.sort_by == "title":
                    sort_field = "title.keyword"
                elif search_request.sort_by == "rating":
                    sort_field = "rating"
                elif search_request.sort_by == "release_date":
                    # For multi-index search, use a script that considers both date fields.
                    sort_field = {
                        "_script": {
                            "type": "number",
                            "script": {
                                "source": "doc.containsKey('release_date') && !doc['release_date'].empty ? doc['release_date'].value.millis : (doc.containsKey('first_air_date') && !doc['first_air_date'].empty ? doc['first_air_date'].value.millis : 0)"
                            },
                            "order": sort_order,
                        }
                    }
                elif search_request.sort_by == "popularity":
                    sort_field = (
                        "_score"  # Fall back to score since popularity may not exist
                    )

            if search_request.sort_order:
                sort_order = search_request.sort_order

            # Build sort array - handle missing fields gracefully
            sort_array = [{"_score": {"order": "desc"}}]
            if sort_field != "_score":
                if isinstance(sort_field, str):
                    sort_array.append(
                        {sort_field: {"order": sort_order, "unmapped_type": "float"}}
                    )
                else:
                    sort_array.append(sort_field)

            # Execute the Elasticsearch query across multiple indices.
            response = await self.client.search(
                index=indices,
                body={
                    "query": search_query,
                    "from": offset,
                    "size": search_request.per_page,
                    "sort": sort_array,
                    "highlight": {
                        "fields": {
                            "title": {},
                            "original_title": {},
                            "description": {"fragment_size": 150},
                        }
                    },
                },
            )

            hits = []
            for hit in response["hits"]["hits"]:
                content_data = hit["_source"]
                # Rename "id" field to "guid" for schema compatibility.
                if "id" in content_data:
                    content_data["guid"] = content_data.pop("id")
                content_data["score"] = hit["_score"]
                content_data["_index"] = hit["_index"]  # index info for the frontend
                if "highlight" in hit:
                    content_data["highlight"] = hit["highlight"]
                hits.append(content_data)

            # Pagination berechnen
            total = response["hits"]["total"]["value"]
            total_pages = (
                total + search_request.per_page - 1
            ) // search_request.per_page

            # Timing berechnen
            took = int((time.time() - start_time) * 1000)  # in Millisekunden

            return {
                "hits": hits,
                "total": total,
                "page": search_request.page,
                "per_page": search_request.per_page,
                "total_pages": total_pages,
                "query": search_request.query,
                "search_type": search_request.search_type,
                "took": took,
            }

        except Exception as e:
            logger.error("Fehler bei der einheitlichen Suche: %s", e)
            took = int((time.time() - start_time) * 1000)
            return {
                "hits": [],
                "total": 0,
                "page": search_request.page,
                "per_page": search_request.per_page,
                "total_pages": 0,
                "query": search_request.query,
                "search_type": search_request.search_type,
                "took": took,
            }


# Singleton instance for module-level use.
elasticsearch_service = ElasticsearchService()
