import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from pyrate.api.dependencies import CurrentSuperuser, DatabaseSession

logger = logging.getLogger(__name__)
from pyrate.models.media import MediaType
from pyrate.services.elasticsearch import elasticsearch_service
from pyrate.services.media import MediaService

router = APIRouter()


class ReindexResponse(BaseModel):
    """Response model for reindex operations."""

    message: str
    task_id: str | None = None
    status: str


class ReindexStats(BaseModel):
    """Statistics for reindex operations."""

    movies_indexed: int
    shows_indexed: int
    movies_failed: int
    shows_failed: int
    total_time_seconds: float


async def reindex_movies_task(db: DatabaseSession) -> ReindexStats:
    """Background task to reindex all movies."""
    import time

    start_time = time.time()

    try:
        batch_size = 5000
        total_indexed = 0
        total_failed = 0
        offset = 0
        media_service = MediaService(db)

        while True:
            movies = await media_service.list_by_type(
                MediaType.MOVIES, limit=batch_size, offset=offset
            )
            if not movies:
                break

            result = await elasticsearch_service.bulk_index_movies(movies)
            total_indexed += result.get("success", 0)
            total_failed += result.get("failed", 0)
            offset += batch_size
            if len(movies) < batch_size:
                break

        end_time = time.time()
        return ReindexStats(
            movies_indexed=total_indexed,
            shows_indexed=0,
            movies_failed=total_failed,
            shows_failed=0,
            total_time_seconds=end_time - start_time,
        )

    except Exception as e:
        end_time = time.time()  # noqa: F841
        logger.error("Failed to reindex movies: %s", e)
        raise HTTPException(
            status_code=500, detail="Failed to reindex movies"
        )


async def reindex_shows_task(db: DatabaseSession) -> ReindexStats:
    """Background task to reindex all shows."""
    import time

    start_time = time.time()

    try:
        batch_size = 5000
        total_indexed = 0
        total_failed = 0
        offset = 0
        media_service = MediaService(db)

        while True:
            shows = await media_service.list_by_type(
                MediaType.SHOWS, limit=batch_size, offset=offset
            )
            if not shows:
                break

            result = await elasticsearch_service.bulk_index_shows(shows)
            total_indexed += result.get("success", 0)
            total_failed += result.get("failed", 0)
            offset += batch_size
            if len(shows) < batch_size:
                break

        end_time = time.time()
        return ReindexStats(
            movies_indexed=0,
            shows_indexed=total_indexed,
            movies_failed=0,
            shows_failed=total_failed,
            total_time_seconds=end_time - start_time,
        )

    except Exception as e:
        end_time = time.time()  # noqa: F841
        logger.error("Failed to reindex shows: %s", e)
        raise HTTPException(
            status_code=500, detail="Failed to reindex shows"
        )


async def reindex_all_task(db: DatabaseSession) -> ReindexStats:
    """Background task to reindex all movies and shows."""
    import time

    start_time = time.time()
    batch_size = 5000
    media_service = MediaService(db)

    try:
        movies_indexed = 0
        movies_failed = 0
        offset = 0

        while True:
            movies = await media_service.list_by_type(
                MediaType.MOVIES, limit=batch_size, offset=offset
            )
            if not movies:
                break
            result = await elasticsearch_service.bulk_index_movies(movies)
            movies_indexed += result.get("success", 0)
            movies_failed += result.get("failed", 0)
            offset += batch_size
            if len(movies) < batch_size:
                break

        shows_indexed = 0
        shows_failed = 0
        offset = 0

        while True:
            shows = await media_service.list_by_type(
                MediaType.SHOWS, limit=batch_size, offset=offset
            )
            if not shows:
                break
            result = await elasticsearch_service.bulk_index_shows(shows)
            shows_indexed += result.get("success", 0)
            shows_failed += result.get("failed", 0)
            offset += batch_size
            if len(shows) < batch_size:
                break

        end_time = time.time()
        return ReindexStats(
            movies_indexed=movies_indexed,
            shows_indexed=shows_indexed,
            movies_failed=movies_failed,
            shows_failed=shows_failed,
            total_time_seconds=end_time - start_time,
        )

    except Exception as e:
        end_time = time.time()  # noqa: F841
        logger.error("Failed to reindex all media: %s", e)
        raise HTTPException(
            status_code=500, detail="Failed to reindex media"
        )


@router.post("/movies", response_model=ReindexResponse)
async def reindex_movies(
    background_tasks: BackgroundTasks,
    db: DatabaseSession,
    current_user: CurrentSuperuser,
):
    """Start a background task to reindex all movies."""
    try:
        # Verify Elasticsearch connection.
        if not elasticsearch_service.client:
            await elasticsearch_service.initialize()

        if not elasticsearch_service.client:
            raise HTTPException(
                status_code=503, detail="Elasticsearch service unavailable"
            )

        # Schedule the background task.
        background_tasks.add_task(reindex_movies_task, db)

        return ReindexResponse(
            message="Movie reindexing started", status="queued"
        )

    except Exception as e:
        logger.error("Failed to start movie reindex: %s", e)
        raise HTTPException(
            status_code=500,
            detail="Failed to start movie reindexing",
        )


@router.post("/shows", response_model=ReindexResponse)
async def reindex_shows(
    background_tasks: BackgroundTasks,
    db: DatabaseSession,
    current_user: CurrentSuperuser,
):
    """Start a background task to reindex all shows."""
    try:
        # Verify Elasticsearch connection.
        if not elasticsearch_service.client:
            await elasticsearch_service.initialize()

        if not elasticsearch_service.client:
            raise HTTPException(
                status_code=503, detail="Elasticsearch service unavailable"
            )

        # Schedule the background task.
        background_tasks.add_task(reindex_shows_task, db)

        return ReindexResponse(
            message="Show reindexing started", status="queued"
        )

    except Exception as e:
        logger.error("Failed to start show reindex: %s", e)
        raise HTTPException(
            status_code=500,
            detail="Failed to start show reindexing",
        )


@router.post("/all", response_model=ReindexResponse)
async def reindex_all(
    background_tasks: BackgroundTasks,
    db: DatabaseSession,
    current_user: CurrentSuperuser,
):
    """Start a background task to reindex all movies and shows."""
    try:
        # Verify Elasticsearch connection.
        if not elasticsearch_service.client:
            await elasticsearch_service.initialize()

        if not elasticsearch_service.client:
            raise HTTPException(
                status_code=503, detail="Elasticsearch service unavailable"
            )

        # Schedule the background task.
        background_tasks.add_task(reindex_all_task, db)

        return ReindexResponse(
            message="Full reindexing started", status="queued"
        )

    except Exception as e:
        logger.error("Failed to start full reindex: %s", e)
        raise HTTPException(
            status_code=500,
            detail="Failed to start full reindexing",
        )


@router.get("/status", response_model=dict)
async def get_reindex_status(current_user: CurrentSuperuser):
    """Return the status of the Elasticsearch service."""
    try:
        if not elasticsearch_service.client:
            await elasticsearch_service.initialize()

        if elasticsearch_service.client:
            # Check Elasticsearch cluster health.
            health = await elasticsearch_service.client.cluster.health()
            return {
                "elasticsearch_available": True,
                "cluster_status": health.get("status", "unknown"),
                "number_of_nodes": health.get("number_of_nodes", 0),
                "active_shards": health.get("active_shards", 0),
            }
        else:
            return {
                "elasticsearch_available": False,
                "cluster_status": "unavailable",
                "number_of_nodes": 0,
                "active_shards": 0,
            }

    except Exception as e:
        return {
            "elasticsearch_available": False,
            "cluster_status": "error",
            "error": str(e),
            "number_of_nodes": 0,
            "active_shards": 0,
        }
