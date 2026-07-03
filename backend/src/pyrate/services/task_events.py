"""Activity-log helpers for background task status events."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from taskiq.abc.middleware import TaskiqMiddleware

from pyrate.database import sessionmanager
from pyrate.schemas.activity_log import ActivityLogCreate
from pyrate.services.activity_log import ActivityLogService
from pyrate.services.observability import record_worker_task_event as record_task_metric

logger = logging.getLogger(__name__)


def _message_labels(message: Any) -> dict:
    labels = getattr(message, "labels", None)
    return labels if isinstance(labels, dict) else {}


def _message_task_id(message: Any, labels: dict) -> str:
    task_name = getattr(message, "task_name", None)
    raw_task_id = labels.get("pyrate_task_id") or labels.get("task_id") or task_name
    return str(raw_task_id or "unknown")


def _message_category(task_id: str, labels: dict) -> str:
    raw_category = labels.get("pyrate_category") or labels.get("category")
    if raw_category:
        return str(raw_category)
    task_id_lower = task_id.lower()
    if "download" in task_id_lower:
        return "downloads"
    if any(token in task_id_lower for token in ("metadata", "trending", "rating")):
        return "metadata"
    if any(token in task_id_lower for token in ("cleanup", "storage")):
        return "cleanup"
    if any(token in task_id_lower for token in ("recommendation", "similarity")):
        return "recommendations"
    if "reindex" in task_id_lower:
        return "search"
    return "worker"


def _message_run_id(message: Any, labels: dict) -> str:
    run_id = labels.get("pyrate_run_id") or labels.get("run_id")
    if run_id:
        return str(run_id)
    run_id = str(uuid.uuid4())
    try:
        labels["pyrate_run_id"] = run_id
        if hasattr(message, "labels"):
            message.labels = labels
    except Exception:
        pass
    return run_id


def _result_error(result: Any) -> str | None:
    is_error = bool(getattr(result, "is_err", False))
    if not is_error:
        return None
    error = getattr(result, "error", None)
    return str(error or "Task failed")


class WorkerTaskEventMiddleware(TaskiqMiddleware):
    """Record Taskiq lifecycle callbacks in the activity log."""

    async def pre_send(self, message):
        labels = _message_labels(message)
        task_id = _message_task_id(message, labels)
        category = _message_category(task_id, labels)
        run_id = _message_run_id(message, labels)
        await record_worker_task_event(
            task_id=task_id,
            category=category,
            status="queued",
            run_id=run_id,
            message=f"Queued worker task {task_id}",
        )
        return message

    async def post_execute(self, message, result) -> None:
        labels = _message_labels(message)
        task_id = _message_task_id(message, labels)
        category = _message_category(task_id, labels)
        run_id = _message_run_id(message, labels)
        error = _result_error(result)
        status = "failed" if error else "completed"
        await record_worker_task_event(
            task_id=task_id,
            category=category,
            status=status,
            run_id=run_id,
            message=f"{status.title()} worker task {task_id}",
            error=error,
        )


async def record_worker_task_event(
    *,
    task_id: str,
    category: str,
    status: str,
    message: str,
    run_id: str | None = None,
    error: str | None = None,
) -> str:
    """Record a worker task event and return the run id used."""
    if status not in {"queued", "completed", "failed"}:
        raise ValueError(f"Unsupported task status: {status}")

    run_id = run_id or str(uuid.uuid4())
    extra_data = {
        "task_id": task_id,
        "category": category,
        "run_id": run_id,
        "status": status,
    }
    if error:
        extra_data["error"] = error

    record_task_metric(task_id=task_id, category=category, status=status)

    try:
        async with sessionmanager.session() as db:
            await ActivityLogService(db).create(
                ActivityLogCreate(
                    event_type=f"task.{status}",
                    message=message,
                    severity="error" if status == "failed" else "info",
                    entity_type="task",
                    extra_data=json.dumps(extra_data, sort_keys=True),
                )
            )
    except Exception:
        logger.warning("Failed to record worker task event", exc_info=True)

    return run_id


async def run_tracked_worker_task(
    *,
    task_id: str,
    category: str,
    queued_message: str,
    completed_message: str,
    failed_message: str,
    operation,
) -> None:
    """Run a coroutine while recording queued/completed/failed task events."""
    run_id = await record_worker_task_event(
        task_id=task_id,
        category=category,
        status="queued",
        message=queued_message,
    )
    try:
        await operation()
    except Exception as exc:
        await record_worker_task_event(
            task_id=task_id,
            category=category,
            status="failed",
            run_id=run_id,
            message=failed_message,
            error=str(exc),
        )
        raise
    await record_worker_task_event(
        task_id=task_id,
        category=category,
        status="completed",
        run_id=run_id,
        message=completed_message,
    )
