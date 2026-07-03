"""Taskiq runtime wiring shared by worker task modules."""

from taskiq import TaskiqScheduler
from taskiq.middlewares import SimpleRetryMiddleware
from taskiq.schedule_sources import LabelScheduleSource
from taskiq_redis import RedisAsyncResultBackend, RedisStreamBroker

from pyrate.config import connection_settings, settings
from pyrate.services.task_events import WorkerTaskEventMiddleware
from pyrate.utils.logging import setup_logging

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


def create_scheduler():
    return TaskiqScheduler(broker=broker, sources=[LabelScheduleSource(broker)])
