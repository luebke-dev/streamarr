"""Unit tests for the overlay engine (conditions, context, renderer)."""

from __future__ import annotations

import io
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from PIL import Image

from streamarr.overlays import (
    OverlayRenderError,
    OverlayRenderer,
    build_render_context,
    evaluate_condition,
    resolution_label,
)
from streamarr.overlays.renderer import (
    _format_placeholders,
    _parse_color,
    _resolve_axis,
    iter_template_entries,
)


# ---------------------------------------------------------------------------
# Context builder
# ---------------------------------------------------------------------------


def _file(width=None, height=None, codec=None, audio_codec=None):
    return SimpleNamespace(
        width=width, height=height, codec=codec, audio_codec=audio_codec
    )


def _item(
    *,
    media_type="MOVIES",
    title="Foo",
    year=2020,
    genres=("Action",),
    files=(),
    min_age=None,
    availability="available",
):
    return SimpleNamespace(
        media_type=SimpleNamespace(value=media_type),
        title=title,
        release_date=datetime(year, 6, 1, tzinfo=UTC) if year else None,
        genres=[SimpleNamespace(name=g) for g in genres],
        files=list(files),
        min_age=min_age,
        availability_status=SimpleNamespace(value=availability),
    )


class TestContextBuilder:
    def test_basic_fields(self):
        ctx = build_render_context(_item(year=1999, genres=("Sci-Fi", "Action")))
        assert ctx["title"] == "Foo"
        assert ctx["year"] == 1999
        assert ctx["genres"] == ["sci-fi", "action"]
        assert ctx["media_type"] == "MOVIES"
        assert ctx["availability"] == "available"

    def test_resolution_picks_max_height(self):
        files = (_file(width=1920, height=1080), _file(width=3840, height=2160))
        ctx = build_render_context(_item(files=files))
        assert ctx["resolution.height"] == 2160
        assert ctx["resolution.width"] == 3840
        assert ctx["resolution.label"] == "4K"

    def test_resolution_label_buckets(self):
        assert resolution_label(2160) == "4K"
        assert resolution_label(1080) == "1080p"
        assert resolution_label(720) == "720p"
        assert resolution_label(0) is None
        assert resolution_label(None) is None

    def test_codecs_from_files(self):
        ctx = build_render_context(
            _item(files=(_file(codec="hevc", audio_codec="eac3"),))
        )
        assert "hevc" in ctx["codecs.video"]
        assert "eac3" in ctx["codecs.audio"]


# ---------------------------------------------------------------------------
# Condition DSL
# ---------------------------------------------------------------------------


class TestConditionDsl:
    def test_empty_is_true(self):
        assert evaluate_condition({}, {}) is True
        assert evaluate_condition(None, {}) is True

    def test_leaf_operators(self):
        ctx = {"x": 10, "label": "Hello", "tags": ["a", "b"]}
        assert evaluate_condition({"field": "x", "op": "gte", "value": 5}, ctx)
        assert not evaluate_condition({"field": "x", "op": "lt", "value": 5}, ctx)
        assert evaluate_condition(
            {"field": "label", "op": "eq", "value": "Hello"}, ctx
        )
        assert evaluate_condition(
            {"field": "label", "op": "matches", "value": "hel.o"}, ctx
        )
        assert evaluate_condition(
            {"field": "tags", "op": "contains", "value": "A"}, ctx
        )
        assert not evaluate_condition(
            {"field": "tags", "op": "not_contains", "value": "A"}, ctx
        )

    def test_in_and_not_in_with_list_actual(self):
        ctx = {"genres": ["action", "drama"]}
        assert evaluate_condition(
            {"field": "genres", "op": "in", "value": ["action"]}, ctx
        )
        assert not evaluate_condition(
            {"field": "genres", "op": "not_in", "value": ["action"]}, ctx
        )

    def test_compound(self):
        ctx = {"resolution.height": 2160, "media_type": "MOVIES"}
        expr = {
            "all": [
                {"field": "resolution.height", "op": "gte", "value": 2160},
                {
                    "any": [
                        {"field": "media_type", "op": "eq", "value": "MOVIES"},
                        {"field": "media_type", "op": "eq", "value": "SHOWS"},
                    ]
                },
            ]
        }
        assert evaluate_condition(expr, ctx)

    def test_not(self):
        ctx = {"x": 1}
        assert evaluate_condition(
            {"not": {"field": "x", "op": "eq", "value": 2}}, ctx
        )

    def test_unknown_field_yields_false(self):
        # Comparing a missing field should never raise.
        ctx = {}
        assert not evaluate_condition(
            {"field": "nope", "op": "gte", "value": 1}, ctx
        )
        assert not evaluate_condition(
            {"field": "nope", "op": "matches", "value": ".*"}, ctx
        )


# ---------------------------------------------------------------------------
# Renderer helpers
# ---------------------------------------------------------------------------


class TestRendererHelpers:
    def test_resolve_axis_anchors(self):
        # canvas=1000, element=200, padding=20
        assert _resolve_axis("left", 1000, 200, 20) == 20
        assert _resolve_axis("right", 1000, 200, 20) == 780
        assert _resolve_axis("center", 1000, 200, 20) == 400
        assert _resolve_axis(150, 1000, 200, 20) == 150
        # Unknown token falls back to padding
        assert _resolve_axis("bogus", 1000, 200, 20) == 20

    def test_format_placeholders(self):
        ctx = {"resolution.label": "4K", "title": "Foo", "tags": ["a", "b"]}
        assert _format_placeholders("{resolution.label}", ctx) == "4K"
        assert _format_placeholders("{title} HDR", ctx) == "Foo HDR"
        assert _format_placeholders("{tags}", ctx) == "a, b"
        assert _format_placeholders("{missing}", ctx) == ""

    def test_parse_color_handles_alpha_and_invalid(self):
        assert _parse_color("#ffffff") == (255, 255, 255, 255)
        assert _parse_color("#000000ff") == (0, 0, 0, 255)
        assert _parse_color("not-a-color")[3] == 255  # fallback white


# ---------------------------------------------------------------------------
# Renderer E2E (no DB)
# ---------------------------------------------------------------------------


def _blank_jpeg(width=400, height=600, color=(20, 20, 20)) -> bytes:
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _text_template(guid="t1", text="4K", x="right", y="top"):
    return SimpleNamespace(
        guid=guid,
        version=1,
        z_order=0,
        elements=[
            {
                "type": "text",
                "text": text,
                "x": x,
                "y": y,
                "padding": 14,
                "font_size": 32,
                "color": "#ffffff",
                "background": "#000000aa",
                "background_radius": 6,
            }
        ],
    )


class TestRendererE2E:
    def test_render_text_overlay_produces_jpeg(self):
        base = _blank_jpeg()
        renderer = OverlayRenderer()
        entries = iter_template_entries([_text_template()])
        result = renderer.render(base, entries, {"resolution.label": "4K"})
        # Result must be a valid JPEG
        image = Image.open(io.BytesIO(result.data))
        assert image.format == "JPEG"
        assert image.size == (400, 600)
        assert result.rendered_count == 1
        assert result.skipped_count == 0
        assert len(result.source_hash) == 64

    def test_hash_changes_with_template_version(self):
        base = _blank_jpeg()
        renderer = OverlayRenderer()
        template = _text_template()
        entries_v1 = iter_template_entries([template])
        h1 = renderer.compute_hash(base, entries_v1)

        template.version = 2
        entries_v2 = iter_template_entries([template])
        h2 = renderer.compute_hash(base, entries_v2)
        assert h1 != h2

    def test_hash_changes_with_base_bytes(self):
        renderer = OverlayRenderer()
        template = _text_template()
        entries = iter_template_entries([template])
        h1 = renderer.compute_hash(_blank_jpeg(color=(0, 0, 0)), entries)
        h2 = renderer.compute_hash(_blank_jpeg(color=(255, 0, 0)), entries)
        assert h1 != h2

    def test_render_skips_unknown_element(self):
        base = _blank_jpeg()
        template = SimpleNamespace(
            guid="t1",
            version=1,
            z_order=0,
            elements=[{"type": "bogus", "x": 0, "y": 0}],
        )
        renderer = OverlayRenderer()
        entries = iter_template_entries([template])
        result = renderer.render(base, entries, {})
        assert result.rendered_count == 0
        assert result.skipped_count == 1

    def test_render_raises_on_bad_base(self):
        renderer = OverlayRenderer()
        entries = iter_template_entries([_text_template()])
        with pytest.raises(OverlayRenderError):
            renderer.render(b"definitely-not-an-image", entries, {})
