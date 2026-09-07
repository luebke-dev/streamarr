"""Taskiq runtime wiring shared by worker task modules."""

import logging
import os

from prometheus_client import Gauge, start_http_server
from taskiq import TaskiqEvents, TaskiqScheduler, TaskiqState
from taskiq.middlewares import SimpleRetryMiddleware
from taskiq.schedule_sources import LabelScheduleSource
from taskiq_redis import RedisAsyncResultBackend, RedisStreamBroker

from streamarr.config import connection_settings, load_settings_from_database, settings
from streamarr.services.task_events import WorkerTaskEventMiddleware
from streamarr.utils.logging import setup_logging

logger = logging.getLogger(__name__)

# Marks that the worker's Prometheus metrics HTTP server is up. Task
# throughput / failures are already recorded on the default registry via
# ``WORKER_TASK_EVENTS`` (see services/observability.py + WorkerTaskEventMiddleware);
# they were simply never exposed because only the FastAPI app served /metrics.
WORKER_UP = Gauge(
    "streamarr_worker_up",
    "1 while the Taskiq worker process is running and exposing metrics.",
)

_metrics_server_started = False

setup_logging(
    level=connection_settings.log_level,
    fmt=connection_settings.log_format,
)

result_backend = RedisAsyncResultBackend(
    redis_url=settings.redis_url,
)

# The task stream is unbounded by default: every cron tick is appended and
# nothing ever removes an acknowledged entry, so the key grows without limit
# (it had reached ~138k entries before this cap was added). ``maxlen`` makes
# Redis trim on write. The bound is generous enough to hold a scan's fan-out
# of per-file probe/index tasks while a slow consumer catches up.
_STREAM_MAXLEN = 50_000

broker = (
    RedisStreamBroker(url=settings.redis_url, maxlen=_STREAM_MAXLEN)
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


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def _start_worker_metrics_server(_state: TaskiqState) -> None:
    """Expose the worker's Prometheus default registry over HTTP.

    The worker process records domain metrics (``WORKER_TASK_EVENTS`` task
    throughput/failures, indexer/download counters, sampler stats, …) on the
    prometheus_client default registry, but nothing served them — only the
    FastAPI app exposed ``/metrics``. This starts a minimal metrics HTTP server
    so Prometheus can scrape task throughput/errors from the worker too.

    Port comes from ``WORKER_METRICS_PORT`` (default 9100). Guarded so a reload
    (address already in use) or a bind failure never crashes the worker.
    """
    global _metrics_server_started
    if _metrics_server_started:
        return
    port = int(os.getenv("WORKER_METRICS_PORT", "9100"))
    try:
        start_http_server(port)
    except Exception:
        logger.warning(
            "Failed to start worker metrics server on port %s", port, exc_info=True
        )
        return
    _metrics_server_started = True
    WORKER_UP.set(1)
    logger.info("Worker metrics server listening on :%s/metrics", port)


def create_scheduler():
    return TaskiqScheduler(broker=broker, sources=[LabelScheduleSource(broker)])
