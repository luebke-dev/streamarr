"""Poster/backdrop overlay engine.

Public API:

  * ``OverlayService`` — orchestrates the full pipeline for one item:
    pick applicable templates, build the render context, hash the
    inputs, dispatch to the renderer, and persist
    ``OverlayApplication`` rows.
  * ``OverlayRenderer`` — pure PIL composition: given an original image
    plus a list of template element dicts, return rendered bytes.
  * ``evaluate_condition`` — DSL evaluator (used by the service to
    decide which templates apply).
  * ``build_render_context`` — extract the dictionary the conditions
    DSL and text-element placeholders read from.
"""

from streamarr.overlays.conditions import evaluate_condition
from streamarr.overlays.context import build_render_context, resolution_label
from streamarr.overlays.renderer import OverlayRenderError, OverlayRenderer
from streamarr.overlays.service import OverlayApplyResult, OverlayService

__all__ = [
    "OverlayApplyResult",
    "OverlayRenderError",
    "OverlayRenderer",
    "OverlayService",
    "build_render_context",
    "evaluate_condition",
    "resolution_label",
]
