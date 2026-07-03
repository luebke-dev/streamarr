"""PIL-based overlay renderer.

Inputs:
  * ``base_bytes`` — original poster bytes (any PIL-readable format).
  * ``template_entries`` — ordered list of
    ``(template_guid, version, elements)`` triples to composite, lowest
    ``z_order`` first.
  * ``context`` — render context dict (powers placeholder substitution
    inside ``TextElement.text``).

Output: rendered JPEG bytes plus the SHA-256 ``source_hash`` the caller
uses for cache invalidation.

Element shapes (JSON-serializable, stored in ``OverlayTemplate.elements``)::

    {"type": "text", "text": "4K",
     "x": "right", "y": "top",
     "padding": 12, "font_size": 48,
     "color": "#ffffff", "background": "#000000aa",
     "stroke_width": 2, "stroke_color": "#000000"}

    {"type": "image", "src": "data/overlay_assets/netflix.png",
     "x": "left", "y": "bottom",
     "width": 120, "padding": 16, "opacity": 0.95}

Position values can be:
  * integers (absolute pixels from top-left), or
  * named anchors: ``"left"``/``"center"``/``"right"`` for x,
    ``"top"``/``"center"``/``"bottom"`` for y. Anchors honour the
    element's ``padding``.
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from PIL import Image, ImageColor, ImageDraw, ImageFont

logger = logging.getLogger(__name__)


_PLACEHOLDER_RE = re.compile(r"\{([a-z][a-z0-9_.]*)\}", re.IGNORECASE)

_FONT_SEARCH_PATHS = (
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
    Path("/Library/Fonts/Arial Bold.ttf"),
    Path("/Library/Fonts/Arial.ttf"),
)


class OverlayRenderError(Exception):
    """Raised when an overlay cannot be composited."""


@dataclass(slots=True)
class _PositionedElement:
    """Resolved position + rendered element, ready to paste."""

    image: Image.Image
    x: int
    y: int


@dataclass(slots=True)
class RenderResult:
    """Outcome of :meth:`OverlayRenderer.render`."""

    data: bytes
    source_hash: str
    rendered_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    debug: dict[str, Any] = field(default_factory=dict)


class OverlayRenderer:
    """Compose templates on top of a base poster image."""

    DEFAULT_OUTPUT_FORMAT = "JPEG"
    DEFAULT_QUALITY = 90

    def __init__(
        self,
        *,
        default_font_path: str | None = None,
        asset_root: str | Path | None = None,
    ) -> None:
        self.default_font_path = default_font_path
        self.asset_root = Path(asset_root) if asset_root else None
        self._font_cache: dict[tuple[str | None, int], ImageFont.FreeTypeFont] = {}

    def render(
        self,
        base_bytes: bytes,
        template_entries: Sequence[tuple[Any, int, list[dict]]],
        context: dict[str, Any],
    ) -> RenderResult:
        try:
            base = Image.open(io.BytesIO(base_bytes)).convert("RGBA")
        except (Image.UnidentifiedImageError, OSError) as exc:
            raise OverlayRenderError(f"Base image not decodable: {exc}")

        composite = base.copy()
        rendered = 0
        skipped = 0
        errors = 0
        for _guid, _version, elements in template_entries:
            for element in elements:
                try:
                    positioned = self._build_element(composite, element, context)
                except OverlayRenderError as exc:
                    logger.info("overlay element skipped: %s", exc)
                    skipped += 1
                    errors += 1
                    continue
                if positioned is None:
                    skipped += 1
                    continue
                composite.alpha_composite(positioned.image, dest=(positioned.x, positioned.y))
                rendered += 1

        out = io.BytesIO()
        composite.convert("RGB").save(
            out, format=self.DEFAULT_OUTPUT_FORMAT, quality=self.DEFAULT_QUALITY
        )
        data = out.getvalue()
        return RenderResult(
            data=data,
            source_hash=self.compute_hash(base_bytes, template_entries, context),
            rendered_count=rendered,
            skipped_count=skipped,
            error_count=errors,
            debug={
                "base_size": list(base.size),
                "templates": len(template_entries),
            },
        )

    @staticmethod
    def compute_hash(
        base_bytes: bytes,
        template_entries: Sequence[tuple[Any, int, list[dict]]],
        context: dict[str, Any] | None = None,
    ) -> str:
        """Stable hash for cache invalidation.

        Combines the SHA-256 of the original bytes with each template's
        ``(guid, version)`` tuple so a template-content change forces a
        re-render even though the original is unchanged. Entries are hashed
        in their given (z_order-sorted) order so a reorder invalidates too,
        and resolved text placeholders fold ``context`` in so a metadata
        change re-renders the same base image.
        """
        h = hashlib.sha256()
        h.update(b"v2:")
        h.update(hashlib.sha256(base_bytes).digest())
        for index, (guid, version, elements) in enumerate(template_entries):
            h.update(b"\x1f")
            h.update(str(index).encode("utf-8"))
            h.update(b":")
            h.update(str(guid).encode("utf-8"))
            h.update(b":")
            h.update(str(version).encode("utf-8"))
            if context is None:
                continue
            for element in elements or ():
                raw_text = element.get("text") if isinstance(element, dict) else None
                if raw_text:
                    h.update(b"\x1e")
                    h.update(_format_placeholders(raw_text, context).encode("utf-8"))
        return h.hexdigest()

    # ------------------------------------------------------------------
    # Element construction
    # ------------------------------------------------------------------

    def _build_element(
        self,
        canvas: Image.Image,
        element: dict,
        context: dict[str, Any],
    ) -> _PositionedElement | None:
        kind = (element.get("type") or "").lower()
        if kind == "text":
            return self._build_text(canvas, element, context)
        if kind == "image":
            return self._build_image(canvas, element)
        raise OverlayRenderError(f"Unknown element type: {kind!r}")

    def _build_text(
        self,
        canvas: Image.Image,
        element: dict,
        context: dict[str, Any],
    ) -> _PositionedElement | None:
        raw_text = element.get("text") or ""
        text = _format_placeholders(raw_text, context)
        if not text:
            return None

        font_size = int(element.get("font_size") or 36)
        font_path = element.get("font_path") or self.default_font_path
        font = self._load_font(font_path, font_size)

        padding = int(element.get("padding") or 0)
        stroke_width = int(element.get("stroke_width") or 0)
        stroke_color = element.get("stroke_color")
        color = element.get("color") or "#ffffff"
        background = element.get("background")

        # Measure the text bounding box including stroke.
        bbox = font.getbbox(text, stroke_width=stroke_width)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        box_w = text_w + 2 * padding
        box_h = text_h + 2 * padding

        layer = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        if background:
            radius = int(element.get("background_radius") or 0)
            self._fill_rect(draw, (0, 0, box_w, box_h), background, radius)
        draw.text(
            (padding - bbox[0], padding - bbox[1]),
            text,
            fill=_parse_color(color),
            font=font,
            stroke_width=stroke_width,
            stroke_fill=_parse_color(stroke_color) if stroke_color else None,
        )

        x, y = _resolve_position(element, canvas.size, layer.size)
        return _PositionedElement(layer, x, y)

    def _build_image(
        self, canvas: Image.Image, element: dict
    ) -> _PositionedElement | None:
        src = element.get("src")
        if not src:
            raise OverlayRenderError("Image element missing 'src'")
        path = self._resolve_asset_path(src)
        try:
            asset = Image.open(path).convert("RGBA")
        except (FileNotFoundError, OSError) as exc:
            raise OverlayRenderError(f"Asset not loadable {path!r}: {exc}")

        target_w = element.get("width")
        target_h = element.get("height")
        if target_w or target_h:
            if not target_w:
                target_w = round(asset.width * (target_h / asset.height))
            if not target_h:
                target_h = round(asset.height * (target_w / asset.width))
            asset = asset.resize(
                (int(target_w), int(target_h)), Image.Resampling.LANCZOS
            )

        opacity = float(element.get("opacity") or 1.0)
        if 0.0 <= opacity < 1.0:
            alpha = asset.getchannel("A").point(lambda p: int(p * opacity))
            asset.putalpha(alpha)

        x, y = _resolve_position(element, canvas.size, asset.size)
        return _PositionedElement(asset, x, y)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_font(
        self, path: str | None, size: int
    ) -> ImageFont.FreeTypeFont:
        cache_key = (path, size)
        cached = self._font_cache.get(cache_key)
        if cached is not None:
            return cached
        font: Any
        try:
            if path:
                font = ImageFont.truetype(path, size)
            else:
                font = self._load_default_font(size)
        except (OSError, ValueError):
            font = self._load_default_font(size)
        self._font_cache[cache_key] = font
        return font

    @staticmethod
    def _load_default_font(size: int) -> ImageFont.FreeTypeFont | Any:
        for candidate in _FONT_SEARCH_PATHS:
            if candidate.exists():
                try:
                    return ImageFont.truetype(str(candidate), size)
                except OSError:
                    continue
        # Last-resort fallback — Pillow's bitmap font ignores size, but
        # at least produces *something* and doesn't crash the renderer.
        return ImageFont.load_default()

    def _resolve_asset_path(self, src: str) -> Path:
        path = Path(src)
        if path.is_absolute() or path.exists():
            return path
        if self.asset_root is not None:
            return self.asset_root / src
        return path

    @staticmethod
    def _fill_rect(
        draw: ImageDraw.ImageDraw,
        box: tuple[int, int, int, int],
        color: str,
        radius: int,
    ) -> None:
        rgba = _parse_color(color)
        if radius > 0:
            draw.rounded_rectangle(box, radius=radius, fill=rgba)
        else:
            draw.rectangle(box, fill=rgba)


# ---------------------------------------------------------------------------
# Position resolution
# ---------------------------------------------------------------------------


def _resolve_position(
    element: dict,
    canvas_size: tuple[int, int],
    element_size: tuple[int, int],
) -> tuple[int, int]:
    canvas_w, canvas_h = canvas_size
    el_w, el_h = element_size
    padding = int(element.get("padding") or 0)
    return (
        _resolve_axis(element.get("x"), canvas_w, el_w, padding),
        _resolve_axis(element.get("y"), canvas_h, el_h, padding),
    )


def _resolve_axis(
    value: Any, canvas_extent: int, element_extent: int, padding: int
) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        token = value.lower()
        if token in {"left", "top"}:
            return padding
        if token in {"right", "bottom"}:
            return canvas_extent - element_extent - padding
        if token == "center":
            return max(0, (canvas_extent - element_extent) // 2)
    # Default: top-left with padding.
    return padding


def _parse_color(value: str | None) -> tuple[int, int, int, int]:
    if value is None:
        return (255, 255, 255, 255)
    try:
        rgba = ImageColor.getcolor(value, "RGBA")
    except ValueError:
        rgba = ImageColor.getcolor("#ffffff", "RGBA")
    if isinstance(rgba, tuple) and len(rgba) == 3:
        rgba = (*rgba, 255)
    return rgba


def _format_placeholders(template: str, context: dict[str, Any]) -> str:
    """Substitute ``{field.path}`` markers from ``context``."""

    def replace(match: re.Match) -> str:
        key = match.group(1)
        value = context.get(key)
        if isinstance(value, (list, tuple, set)):
            return ", ".join(str(v) for v in value)
        if value is None:
            return ""
        return str(value)

    return _PLACEHOLDER_RE.sub(replace, template)


def iter_template_entries(
    templates: Iterable[Any],
) -> list[tuple[Any, int, list[dict]]]:
    """Sort templates by ``(z_order, guid)`` and return a renderer-ready list."""
    items: list[tuple[Any, int, list[dict]]] = []
    for template in sorted(
        templates, key=lambda t: (getattr(t, "z_order", 0), str(t.guid))
    ):
        elements = list(getattr(template, "elements", None) or [])
        items.append((template.guid, getattr(template, "version", 1), elements))
    return items
