"""The identify pass has to run before the refreshes it feeds."""

from types import SimpleNamespace

import pytest

from streamarr.services.library_post_scan import PostScanEnqueuers, dispatch_post_scan
from streamarr.services.library_scanner import LibraryReconcileResult


def _library(metadata_providers=("local", "tmdb")):
    return SimpleNamespace(
        type="SHOWS",
        settings={"options": {"metadata_providers": list(metadata_providers)}},
    )


def _order_recorder():
    order: list[str] = []

    def _step(name):
        async def _fn(*args, **kwargs):
            order.append(name)
        return _fn

    return order, _step


@pytest.mark.asyncio
async def test_identify_runs_once_and_before_any_refresh():
    order, step = _order_recorder()
    result = LibraryReconcileResult(added=2, media_item_guids=["a", "b"])

    counts = await dispatch_post_scan(
        _library(),
        result,
        PostScanEnqueuers(identify=step("identify"), metadata=step("metadata")),
    )

    assert counts["identify"] == 1
    # A freshly scanned item has no TMDB id yet, so a refresh queued ahead of
    # the identify pass would simply give up.
    assert order.index("identify") < order.index("metadata")
    assert order.count("identify") == 1


@pytest.mark.asyncio
async def test_a_scan_that_added_nothing_does_not_trigger_identify():
    order, step = _order_recorder()
    result = LibraryReconcileResult(added=0, updated=7, media_item_guids=["a"])

    counts = await dispatch_post_scan(
        _library(), result, PostScanEnqueuers(identify=step("identify"))
    )

    assert counts["identify"] == 0
    assert order == []


@pytest.mark.asyncio
async def test_identify_is_skipped_when_the_library_has_no_providers():
    order, step = _order_recorder()
    library = _library(metadata_providers=())
    result = LibraryReconcileResult(added=1, media_item_guids=["a"])

    counts = await dispatch_post_scan(
        library, result, PostScanEnqueuers(identify=step("identify"))
    )

    assert counts["identify"] == 0


@pytest.mark.asyncio
async def test_nothing_breaks_without_an_identify_enqueuer():
    order, step = _order_recorder()
    result = LibraryReconcileResult(added=1, media_item_guids=["a"])

    counts = await dispatch_post_scan(
        _library(), result, PostScanEnqueuers(metadata=step("metadata"))
    )

    assert counts["identify"] == 0
    assert order == ["metadata"]
