"""Sanity tests for the bundled Kometa-style defaults.

These don't touch the database — they verify the *content* of the
defaults module so a typo in a future PR can't sneak through the seed
migration and into production rows.
"""

from __future__ import annotations

import uuid

import pytest

from streamarr.metadata.list_sources import (
    ListSourceError,
    ListSourceMediaType,
    source_class,
)
from streamarr.schemas.mass_operation import _MassOperationCommon  # noqa: F401
from streamarr.schemas.overlay import OverlayTemplateCreate
from streamarr.schemas.smart_collection import SmartCollectionCreate
from streamarr.smart_collections import build_builder, builder_types
from streamarr.smart_collections.cron import parse_cron
from streamarr.smart_collections.defaults import (
    OVERLAY_DEFAULTS,
    SMART_COLLECTION_DEFAULTS,
    all_default_slugs,
)


# ---------------------------------------------------------------------------
# Identity invariants
# ---------------------------------------------------------------------------


def test_slugs_are_unique():
    slugs = all_default_slugs()
    assert len(slugs) == len(set(slugs))


def test_smart_collection_guids_are_uuids_and_unique():
    guids = [entry["guid"] for entry in SMART_COLLECTION_DEFAULTS]
    assert len(guids) == len(set(guids))
    for guid in guids:
        uuid.UUID(guid)  # raises on garbage


def test_overlay_guids_are_uuids_and_unique():
    guids = [entry["guid"] for entry in OVERLAY_DEFAULTS]
    assert len(guids) == len(set(guids))
    for guid in guids:
        uuid.UUID(guid)


def test_no_overlap_between_smart_and_overlay_guids():
    smart = {entry["guid"] for entry in SMART_COLLECTION_DEFAULTS}
    overlay = {entry["guid"] for entry in OVERLAY_DEFAULTS}
    assert smart.isdisjoint(overlay)


def test_we_actually_ship_a_meaningful_volume():
    # Sanity guard: if a future refactor accidentally truncates the list
    # the test should yell loudly.
    assert len(SMART_COLLECTION_DEFAULTS) >= 50
    assert len(OVERLAY_DEFAULTS) >= 5


# ---------------------------------------------------------------------------
# Smart-collection validity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("entry", SMART_COLLECTION_DEFAULTS, ids=lambda e: e["slug"])
def test_smart_collection_default_validates_against_create_schema(entry):
    # Drop migration-only metadata fields.
    payload = {k: v for k, v in entry.items() if k not in {"guid", "slug"}}
    schema = SmartCollectionCreate(**payload)
    # Cron must parse.
    assert parse_cron(schema.schedule_cron)


@pytest.mark.parametrize("entry", SMART_COLLECTION_DEFAULTS, ids=lambda e: e["slug"])
def test_smart_collection_builder_type_is_registered(entry):
    assert entry["builder_type"] in builder_types()


@pytest.mark.parametrize("entry", SMART_COLLECTION_DEFAULTS, ids=lambda e: e["slug"])
def test_smart_collection_media_type_supported_by_builder(entry):
    builder_type = entry["builder_type"]
    media_type = entry["media_type"]
    if builder_type == "library_filter":
        return  # library_filter supports both
    try:
        cls = source_class(builder_type)
    except ListSourceError:
        pytest.fail(f"Unknown builder {builder_type}")
    enum_value = ListSourceMediaType.MOVIE if media_type == "MOVIE" else ListSourceMediaType.SHOW
    assert enum_value in cls.supported_media_types, (
        f"{entry['slug']}: builder {builder_type} doesn't support {media_type}"
    )


# ---------------------------------------------------------------------------
# Overlay validity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("entry", OVERLAY_DEFAULTS, ids=lambda e: e["slug"])
def test_overlay_default_validates_against_create_schema(entry):
    payload = {k: v for k, v in entry.items() if k not in {"guid", "slug"}}
    OverlayTemplateCreate(**payload)


@pytest.mark.parametrize("entry", OVERLAY_DEFAULTS, ids=lambda e: e["slug"])
def test_overlay_default_has_visible_element(entry):
    elements = entry.get("elements") or []
    assert elements, f"{entry['slug']} has no elements"
    first = elements[0]
    assert first.get("type") in {"text", "image"}


# ---------------------------------------------------------------------------
# Idempotency of the slug → guid mapping
# ---------------------------------------------------------------------------


def test_guid_is_stable_across_calls():
    """The defaults module computes guids via uuid5 — same slug, same guid."""
    from streamarr.smart_collections.defaults import _smart_guid

    first = _smart_guid("tmdb-popular-movies")
    second = _smart_guid("tmdb-popular-movies")
    assert first == second
    assert uuid.UUID(first).version == 5
