from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from streamarr.services.library_post_scan import PostScanEnqueuers, dispatch_post_scan
from streamarr.services.library_scanner import LibraryReconcileResult


@pytest.mark.asyncio
async def test_post_scan_reuses_existing_pipelines_and_library_options():
    library = SimpleNamespace(
        type="MOVIES",
        settings={
            "options": {
                "metadata_providers": ["local", "tmdb"],
                "subtitle_download_enabled": True,
                "subtitle_languages": ["de", "en"],
                "trickplay_enabled": True,
            }
        },
    )
    result = LibraryReconcileResult(
        probe_file_guids=["file-1", "file-1"],
        media_item_guids=["item-1", "item-1"],
    )
    enqueuers = PostScanEnqueuers(
        probe=AsyncMock(),
        metadata=AsyncMock(),
        subtitles=AsyncMock(),
        search_index=AsyncMock(),
    )

    counts = await dispatch_post_scan(library, result, enqueuers)

    assert counts == {
        "probes": 1,
        # Nothing was added, so there is nothing new to identify.
        "identify": 0,
        "metadata": 1,
        "subtitles": 1,
        "search": 1,
    }
    enqueuers.probe.assert_awaited_once_with("file-1")
    enqueuers.metadata.assert_awaited_once_with("item-1")
    enqueuers.subtitles.assert_awaited_once_with("item-1", ["de", "en"])


@pytest.mark.asyncio
async def test_post_scan_honours_disabled_processing_options():
    library = SimpleNamespace(
        type="MOVIES",
        settings={"options": {"trickplay_enabled": False}},
    )
    result = LibraryReconcileResult(
        probe_file_guids=["file-1"], media_item_guids=["item-1"]
    )
    enqueuers = PostScanEnqueuers(
        metadata=AsyncMock(), subtitles=AsyncMock()
    )

    await dispatch_post_scan(library, result, enqueuers)

    enqueuers.metadata.assert_not_awaited()
    enqueuers.subtitles.assert_not_awaited()
