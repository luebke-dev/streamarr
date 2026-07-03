"""Taskiq runtime wiring shared by worker task modules."""

import logging

from taskiq import TaskiqEvents, TaskiqScheduler, TaskiqState
from taskiq.middlewares import SimpleRetryMiddleware
from taskiq.schedule_sources import LabelScheduleSource
from taskiq_redis import RedisAsyncResultBackend, RedisStreamBroker

from pyrate.config import connection_settings, load_settings_from_database, settings
from pyrate.services.task_events import WorkerTaskEventMiddleware
from pyrate.utils.logging import setup_logging

logger = logging.getLogger(__name__)

setup_logging(
    level=connection_settings.log_level,
    fmt=connection_settings.log_format,
)

result_backend = RedisAsyncResultBackend(
    redis_url=settings.redis_url,
)

broker = (
    RedisStreamBroker(url=settings.redis_url)
    .with_result_backend(result_backend)
    .with_middlewares(
        WorkerTaskEventMiddleware(),
        SimpleRetryMiddleware(default_retry_count=3),
    )
)


@broker.on_event(TaskiqEvents.WORKER_STARTUP, TaskiqEvents.CLIENT_STARTUP)
async def _hydrate_settings_from_database(_state: TaskiqState) -> None:
    """Populate the global ``settings`` snapshot from the database.

    The FastAPI app hydrates ``settings`` in its lifespan, but the Taskiq
    worker and scheduler processes never run that code path. Without this
    hook they would only ever see the in-memory defaults (email/transcoding/
    oidc disabled, empty API keys, …) and admin changes stored in the DB
    would be invisible to background jobs. ``WORKER_STARTUP`` fires for the
    worker process and ``CLIENT_STARTUP`` for the scheduler process.
    """
    try:
        await load_settings_from_database()
    except Exception:
        logger.error("Failed to load settings from database", exc_info=True)


def create_scheduler():
    return TaskiqScheduler(broker=broker, sources=[LabelScheduleSource(broker)])
