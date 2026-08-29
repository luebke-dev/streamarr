"""Dispatch existing background capabilities after a library reconciliation."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from streamarr.services.library_paths import library_processing_options
from streamarr.services.library_scanner import LibraryReconcileResult

Enqueue = Callable[..., Awaitable[object]]


@dataclass(slots=True)
class PostScanEnqueuers:
    probe: Enqueue | None = None
    metadata: Enqueue | None = None
    subtitles: Enqueue | None = None
    search_index: Enqueue | None = None


async def dispatch_post_scan(
    library,
    result: LibraryReconcileResult,
    enqueuers: PostScanEnqueuers,
) -> dict[str, int]:
    """Fan out idempotent work according to the library's existing options."""
    options = library_processing_options(library)
    video_or_audio = library.type in {"MOVIES", "SHOWS", "MUSIC", "AUDIOBOOKS"}
    counts = {"probes": 0, "metadata": 0, "subtitles": 0, "search": 0}

    if video_or_audio and enqueuers.probe:
        for file_guid in dict.fromkeys(result.probe_file_guids):
            await enqueuers.probe(file_guid)
            counts["probes"] += 1

    for item_guid in dict.fromkeys(getattr(result, "media_item_guids", [])):
        if enqueuers.search_index:
            await enqueuers.search_index(item_guid)
            counts["search"] += 1
        if options.get("metadata_providers") and enqueuers.metadata:
            await enqueuers.metadata(item_guid)
            counts["metadata"] += 1
        if options.get("subtitle_download_enabled") and enqueuers.subtitles:
            await enqueuers.subtitles(item_guid, options.get("subtitle_languages") or [])
            counts["subtitles"] += 1

    return counts
