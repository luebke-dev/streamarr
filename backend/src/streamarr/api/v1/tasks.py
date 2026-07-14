import asyncio
import importlib
import json
import logging
import math
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.api.dependencies import CurrentSuperuser, DatabaseSession
from streamarr.database import get_db_session, sessionmanager
from streamarr.models.activity_log import ActivityLog
from streamarr.schemas.activity_log import (
    ActivityLogCreate,
    ActivityLogRead,
    PaginatedActivityLogResponse,
)
from streamarr.services.activity_log import ActivityLogService
from streamarr.services.observability import record_worker_task_event

logger = logging.getLogger(__name__)

router = APIRouter()

# Strong refs for fire-and-forget reindex tasks — without this, the asyncio
# event loop only keeps weak refs and the task can be garbage-collected
# mid-flight.
_background_tasks: set[asyncio.Task] = set()


async def _record_task_event(
    db: AsyncSession,
    *,
    event_type: str,
    task_info: "TaskInfo",
    actor_guid,
    run_id: str,
    message: str,
    error: str | None = None,
) -> None:
    extra_data = {
        "task_id": task_info.id,
        "category": task_info.category,
        "run_id": run_id,
        "status": event_type.removeprefix("task."),
    }
    if error:
        extra_data["error"] = error
    record_worker_task_event(
        task_id=task_info.id,
        category=task_info.category,
        status=extra_data["status"],
    )
    await ActivityLogService(db).create(
        ActivityLogCreate(
            event_type=event_type,
            message=message,
            severity="error" if event_type == "task.failed" else "info",
            entity_type="task",
            extra_data=json.dumps(extra_data, sort_keys=True),
        ),
        actor_guid=actor_guid,
    )


def _spawn_background(coro, name: str, task_info: "TaskInfo", actor_guid, run_id: str) -> None:
    async def _runner():
        try:
            await coro

            async with sessionmanager.session() as db:
                await _record_task_event(
                    db,
                    event_type="task.completed",
                    task_info=task_info,
                    actor_guid=actor_guid,
                    run_id=run_id,
                    message=f"Task '{task_info.name}' completed",
                )
        except Exception:
            logger.exception("Background task %s failed", name)

            async with sessionmanager.session() as db:
                await _record_task_event(
                    db,
                    event_type="task.failed",
                    task_info=task_info,
                    actor_guid=actor_guid,
                    run_id=run_id,
                    message=f"Task '{task_info.name}' failed",
                    error="Background task failed",
                )

    task = asyncio.create_task(_runner(), name=name)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


class TaskInfo(BaseModel):
    id: str
    name: str
    description: str
    category: str
    has_args: bool = False


class TaskRunResponse(BaseModel):
    task_id: str
    run_id: str
    message: str


class TaskRunStatusResponse(BaseModel):
    run_id: str
    task_id: str | None = None
    category: str | None = None
    status: str
    queued_at: str | None = None
    completed_at: str | None = None
    failed_at: str | None = None
    latest_message: str | None = None
    error: str | None = None
    events: list[ActivityLogRead]


AVAILABLE_TASKS: list[TaskInfo] = [
    TaskInfo(
        id="refresh_downloads",
        name="Refresh Downloads",
        description="Check all active downloads for status updates from the configured download clients.",
        category="downloads",
    ),
    TaskInfo(
        id="import_trending_movies",
        name="Trending Movies Refresh",
        description="Fetch the latest trending movies from TMDB and update the trending list.",
        category="metadata",
    ),
    TaskInfo(
        id="import_trending_shows",
        name="Trending Shows Refresh",
        description="Fetch the latest trending TV shows from TMDB and update the trending list.",
        category="metadata",
    ),
    TaskInfo(
        id="import_trending_games",
        name="Trending Games Refresh",
        description="Fetch the latest trending games from IGDB and update the trending list.",
        category="metadata",
    ),
    TaskInfo(
        id="import_trending_music",
        name="Trending Music Refresh",
        description="Fetch the latest trending albums from Spotify Charts and update the trending list.",
        category="metadata",
    ),
    TaskInfo(
        id="cleanup_orphaned_temp_files",
        name="Clean Orphaned Temp Files",
        description="Remove orphaned transcoding temp files (.ts, .m3u8) older than 2 hours.",
        category="cleanup",
    ),
    TaskInfo(
        id="retry_stuck_downloads",
        name="Retry Stuck Downloads",
        description="Re-dispatch downloads that were never handed to a downloader, and fail the ones that never will be.",
        category="cleanup",
    ),
    TaskInfo(
        id="cleanup_trickplay_cache",
        name="Clean Trickplay Cache",
        description="Drop cached seek-bar thumbnails whose source file no longer exists in the library.",
        category="cleanup",
    ),
    TaskInfo(
        id="cleanup_stale_transcoding_sessions",
        name="Clean Stale Transcoding Sessions",
        description="Remove stale transcoding sessions from Redis whose containers are no longer running.",
        category="cleanup",
    ),
    TaskInfo(
        id="cleanup_storage",
        name="Full Storage Cleanup",
        description="Run a full storage cleanup: temp files, old download records, orphaned media files, and duplicates.",
        category="cleanup",
    ),
    TaskInfo(
        id="reindex_all",
        name="Reindex All Media (Elasticsearch)",
        description="Reindex all movies and shows in Elasticsearch to update the search index.",
        category="search",
    ),
    TaskInfo(
        id="reindex_movies",
        name="Reindex Movies (Elasticsearch)",
        description="Reindex all movies in Elasticsearch.",
        category="search",
    ),
    TaskInfo(
        id="reindex_shows",
        name="Reindex Shows (Elasticsearch)",
        description="Reindex all TV shows in Elasticsearch.",
        category="search",
    ),
    TaskInfo(
        id="backfill_age_ratings",
        name="Backfill Age Ratings",
        description="Fetch TMDB certifications for every movie/show that is missing a min_age.",
        category="metadata",
    ),
]


@router.get("/diagnostics/slow-queries")
async def get_slow_queries(
    db: DatabaseSession,
    _: CurrentSuperuser,
    limit: int = 20,
) -> list[dict]:
    """Top-N slowest queries by total time from pg_stat_statements.

    Returned on-demand so the superuser can see which queries actually hurt.
    Requires the ``pg_stat_statements`` Postgres extension (loaded via
    ``shared_preload_libraries`` in docker-compose).
    """
    try:
        result = await db.execute(
            text(
                """
                SELECT
                    calls,
                    round(total_exec_time::numeric, 1) AS total_ms,
                    round(mean_exec_time::numeric, 2) AS mean_ms,
                    rows,
                    left(query, 400) AS query
                FROM pg_stat_statements
                WHERE query NOT LIKE 'EXPLAIN%'
                  AND query NOT LIKE '%pg_stat_statements%'
                ORDER BY total_exec_time DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        )
        return [dict(row._mapping) for row in result.all()]
    except Exception as e:
        logger.error("pg_stat_statements unavailable: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="pg_stat_statements not loaded; recreate db container",
        )


@router.get("", response_model=list[TaskInfo])
async def list_tasks(current_user: CurrentSuperuser):
    """List all available background tasks that can be triggered manually."""
    return AVAILABLE_TASKS


@router.get("/history", response_model=PaginatedActivityLogResponse)
async def list_task_history(
    current_user: CurrentSuperuser,  # noqa: ARG001
    db: DatabaseSession,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    status_filter: str = Query("all", alias="status"),
):
    """List task status history from the activity log."""
    allowed_statuses = {"all", "queued", "completed", "failed"}
    if status_filter not in allowed_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid task history status: {status_filter}",
        )

    skip = (page - 1) * per_page
    if status_filter == "all":
        # Combine the three task event types in a single ordered, paginated
        # SQL query so ``total``/``total_pages`` stay consistent with what
        # paging returns even past the old 1000-row-per-type window.
        task_filters = (
            ActivityLog.entity_type == "task",
            ActivityLog.event_type.in_(
                ("task.queued", "task.completed", "task.failed")
            ),
        )
        total = (
            await db.scalar(
                select(func.count(ActivityLog.guid)).where(*task_filters)
            )
            or 0
        )
        result = await db.execute(
            select(ActivityLog)
            .where(*task_filters)
            .order_by(ActivityLog.created_at.desc())
            .offset(skip)
            .limit(per_page)
        )
        entries = list(result.scalars().all())
    else:
        entries, total = await ActivityLogService(db).list(
            skip=skip,
            limit=per_page,
            event_type=f"task.{status_filter}",
            entity_type="task",
        )
    return PaginatedActivityLogResponse(
        items=[ActivityLogRead.model_validate(entry) for entry in entries],
        total=total,
        page=page,
        per_page=per_page,
        total_pages=math.ceil(total / per_page) if total > 0 else 1,
    )


def _task_event_extra(entry) -> dict:
    if not entry.extra_data:
        return {}
    try:
        parsed = json.loads(entry.extra_data)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


@router.get("/history/{run_id}", response_model=TaskRunStatusResponse)
async def get_task_run_history(
    run_id: str,
    current_user: CurrentSuperuser,  # noqa: ARG001
    db: DatabaseSession,
):
    """Return the lifecycle events and current status for one task run."""
    # Narrow the scan to rows whose serialized ``extra_data`` carries this
    # run_id instead of pulling a fixed 3000-row window (which made older runs
    # unreachable). ``extra_data`` is ``json.dumps(..., sort_keys=True)`` so the
    # run_id renders as ``"run_id": "<id>"``; escape LIKE metacharacters.
    escaped_run_id = (
        run_id.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )
    like_pattern = f'%"run_id": "{escaped_run_id}"%'
    result = await db.execute(
        select(ActivityLog)
        .where(
            ActivityLog.entity_type == "task",
            ActivityLog.event_type.in_(
                ("task.queued", "task.completed", "task.failed")
            ),
            ActivityLog.extra_data.like(like_pattern, escape="\\"),
        )
        .order_by(ActivityLog.created_at.asc())
    )
    # Confirm the exact run_id (the LIKE is a substring prefilter).
    events = [
        entry
        for entry in result.scalars().all()
        if _task_event_extra(entry).get("run_id") == run_id
    ]
    if not events:
        raise HTTPException(status_code=404, detail="Task run not found")

    events.sort(key=lambda entry: entry.created_at)
    latest = events[-1]
    latest_extra = _task_event_extra(latest)
    status_value = latest_extra.get("status") or latest.event_type.removeprefix("task.")

    queued_at = None
    completed_at = None
    failed_at = None
    for event in events:
        if event.event_type == "task.queued":
            queued_at = event.created_at.isoformat()
        elif event.event_type == "task.completed":
            completed_at = event.created_at.isoformat()
        elif event.event_type == "task.failed":
            failed_at = event.created_at.isoformat()

    return TaskRunStatusResponse(
        run_id=run_id,
        task_id=latest_extra.get("task_id"),
        category=latest_extra.get("category"),
        status=status_value,
        queued_at=queued_at,
        completed_at=completed_at,
        failed_at=failed_at,
        latest_message=latest.message,
        error=latest_extra.get("error"),
        events=[ActivityLogRead.model_validate(entry) for entry in reversed(events)],
    )


@router.post("/{task_id}/run", response_model=TaskRunResponse)
async def run_task(
    task_id: str,
    current_user: CurrentSuperuser,
    db: AsyncSession | None = Depends(get_db_session),
):
    """Trigger a background task by ID."""
    task_info = next((t for t in AVAILABLE_TASKS if t.id == task_id), None)
    if not task_info:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

    run_id = str(uuid.uuid4())

    try:
        worker_task_ids = {
            "refresh_downloads",
            "import_trending_movies",
            "import_trending_shows",
            "import_trending_games",
            "import_trending_music",
            "cleanup_orphaned_temp_files",
            "retry_stuck_downloads",
            "cleanup_trickplay_cache",
            "cleanup_stale_transcoding_sessions",
            "cleanup_storage",
            "backfill_age_ratings",
        }
        reindex_tasks = {
            "reindex_all": "reindex_all_task",
            "reindex_movies": "reindex_movies_task",
            "reindex_shows": "reindex_shows_task",
        }
        if task_id in worker_task_ids:
            worker_module = importlib.import_module("streamarr.worker")
            await getattr(worker_module, task_id).kiq()
        elif task_id in reindex_tasks:
            reindex_module = importlib.import_module("streamarr.api.v1.reindex")
            reindex_task = getattr(reindex_module, reindex_tasks[task_id])

            async def _run():
                async with sessionmanager.session() as reindex_db:
                    await reindex_task(reindex_db)

            _spawn_background(_run(), task_id, task_info, current_user.guid, run_id)
        else:
            raise HTTPException(
                status_code=400, detail=f"Task '{task_id}' is not runnable"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to start task '%s': %s", task_id, e)
        if isinstance(db, AsyncSession):
            await _record_task_event(
                db,
                event_type="task.failed",
                task_info=task_info,
                actor_guid=current_user.guid,
                run_id=run_id,
                message=f"Task '{task_info.name}' failed to start",
                error=str(e),
            )
        raise HTTPException(
            status_code=500, detail="Failed to start task"
        ) from e

    if isinstance(db, AsyncSession):
        await _record_task_event(
            db,
            event_type="task.queued",
            task_info=task_info,
            actor_guid=current_user.guid,
            run_id=run_id,
            message=f"Task '{task_info.name}' was queued",
        )

    return TaskRunResponse(
        task_id=task_id,
        run_id=run_id,
        message=f"Task '{task_info.name}' has been queued successfully.",
    )
