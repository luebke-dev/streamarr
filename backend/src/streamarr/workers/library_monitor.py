"""Worker-process filesystem monitor that only triggers canonical scans."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from taskiq import TaskiqEvents, TaskiqState
from watchfiles import awatch

from streamarr.database import sessionmanager
from streamarr.services.library import LibraryService
from streamarr.services.library_paths import library_root_paths
from streamarr.services.settings import SettingsService
from streamarr.workers.runtime import broker

logger = logging.getLogger(__name__)
_monitor_task: asyncio.Task | None = None


async def _configured_roots() -> dict[str, list[str]]:
    async with sessionmanager.session() as db:
        enabled = bool(
            await SettingsService(db).get("automation.realtime_library_monitor", True)
        )
        if not enabled:
            return {}
        libraries = await LibraryService(db).list_libraries(enabled_only=True)
        return {
            str(library.guid): [
                root for root in library_root_paths(library) if Path(root).is_dir()
            ]
            for library in libraries
        }


async def monitor_library_changes() -> None:
    """Watch roots in batches; errors simply fall back to scheduled scans."""
    while True:
        roots_by_library = await _configured_roots()
        watched_roots = sorted({root for roots in roots_by_library.values() for root in roots})
        if not watched_roots:
            await asyncio.sleep(30)
            continue
        try:
            async for changes in awatch(
                *watched_roots,
                debounce=1500,
                step=300,
                recursive=True,
                rust_timeout=300_000,
                yield_on_timeout=True,
            ):
                # Periodically rebuild the watcher so library/settings changes
                # take effect without restarting the worker.
                if not changes:
                    break
                changed_paths = [Path(path).resolve(strict=False) for _change, path in changes]
                affected: set[str] = set()
                for library_guid, roots in roots_by_library.items():
                    if any(
                        changed == Path(root) or changed.is_relative_to(Path(root))
                        for changed in changed_paths
                        for root in roots
                    ):
                        affected.add(library_guid)
                if affected:
                    from streamarr.worker import scan_changed_library

                    for library_guid in affected:
                        await scan_changed_library.kiq(library_guid)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning(
                "Realtime library monitor failed; scheduled scan remains active",
                exc_info=True,
            )
            await asyncio.sleep(10)


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def start_library_monitor(_state: TaskiqState) -> None:
    global _monitor_task
    if _monitor_task is None or _monitor_task.done():
        _monitor_task = asyncio.create_task(
            monitor_library_changes(), name="library-change-monitor"
        )


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def stop_library_monitor(_state: TaskiqState) -> None:
    global _monitor_task
    if _monitor_task:
        _monitor_task.cancel()
        await asyncio.gather(_monitor_task, return_exceptions=True)
        _monitor_task = None
