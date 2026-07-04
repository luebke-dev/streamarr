"""Single loader for the ``MediaItem.extra_data`` JSON blob.

``extra_data`` may be a dict, a JSON string, or ``None``. Every consumer had
its own byte-identical copy of this parse; this is the one place that decodes
it, so a schema change to that field is fixed in exactly one spot.
"""

import json
from typing import Any


def load_extra_data(media_item: Any) -> dict[str, Any]:
    """Return ``media_item.extra_data`` as a dict (``{}`` if missing/invalid)."""
    raw = getattr(media_item, "extra_data", None)
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return {}
    return raw if isinstance(raw, dict) else {}
