"""Filter DSL for smart collections (and mass-operations).

Filters apply *after* refs have been resolved to local ``MediaItem``
rows. The DSL is intentionally flat (no AND/OR boolean tree for MVP) —
each top-level key combines with AND semantics. Filters are evaluated
in Python over the resolved item set, which is bounded by the rule's
``item_limit`` (≤ a few hundred items per run in practice).

Mass-operations need to *select* matching items rather than filter an
already-resolved set, so the same DSL is translated to SQL by
``apply_media_filters_to_query``. The keys map 1:1; behaviour matches
the in-memory version on every overlapping field.

Supported keys (all optional):

  * ``min_rating`` / ``max_rating`` — float; read from
    ``ExternalRef.extra['vote_average']`` (TMDb's field). Items without
    a numeric rating are dropped when ``min_rating`` is set.
  * ``min_year`` / ``max_year`` — int; from ``MediaItem.release_date``,
    falling back to ``ExternalRef.year``.
  * ``min_age`` / ``max_age`` — int; from ``MediaItem.min_age``.
  * ``availability`` — list[str] of allowed
    ``AvailabilityStatus`` values.
  * ``genre_in`` / ``genre_not_in`` — list[str] (case-insensitive);
    matches ``MediaItem.genres[*].name``. Requires the genres
    relationship to be eager-loaded.
  * ``language`` — list[str] of allowed
    ``ExternalRef.extra['original_language']`` codes.
  * ``require_files`` — bool; when true, items without files are
    dropped (requires ``files`` to be eager-loaded).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, exists, extract, func, select

from pyrate.metadata.list_sources import ExternalRef
from pyrate.models.media import MediaItem, media_genre_table
from pyrate.models.genre import Genre


def filter_resolved(
    pairs: list[tuple[ExternalRef, MediaItem]],
    rules: dict[str, Any] | None,
) -> list[tuple[ExternalRef, MediaItem]]:
    """Return only the (ref, item) pairs that pass ``rules``."""
    if not rules:
        return pairs

    min_rating = _as_float(rules.get("min_rating"))
    max_rating = _as_float(rules.get("max_rating"))
    min_year = _as_int(rules.get("min_year"))
    max_year = _as_int(rules.get("max_year"))
    min_age = _as_int(rules.get("min_age"))
    max_age = _as_int(rules.get("max_age"))
    availability = _as_str_set(rules.get("availability"))
    languages = _as_str_set(rules.get("language"))
    genre_in = _as_lower_set(rules.get("genre_in"))
    genre_not_in = _as_lower_set(rules.get("genre_not_in"))
    require_files = bool(rules.get("require_files"))

    kept: list[tuple[ExternalRef, MediaItem]] = []
    for ref, item in pairs:
        if not _passes_rating(ref, min_rating, max_rating):
            continue
        if not _passes_year(ref, item, min_year, max_year):
            continue
        if min_age is not None and (item.min_age or 0) < min_age:
            continue
        if max_age is not None and (item.min_age or 999) > max_age:
            continue
        if (
            availability
            and getattr(item.availability_status, "value", item.availability_status)
            not in availability
        ):
            continue
        if languages:
            lang = ref.extra.get("original_language")
            if not lang or lang not in languages:
                continue
        if genre_in or genre_not_in:
            item_genres = {g.name.lower() for g in (item.genres or [])}
            if genre_in and not (item_genres & genre_in):
                continue
            if genre_not_in and (item_genres & genre_not_in):
                continue
        if require_files and not (item.files or []):
            continue
        kept.append((ref, item))
    return kept


# --- helpers ----------------------------------------------------------------


def _passes_rating(
    ref: ExternalRef, lo: float | None, hi: float | None
) -> bool:
    if lo is None and hi is None:
        return True
    rating = ref.extra.get("vote_average")
    if rating is None:
        return lo is None  # no rating → only ok when no minimum demanded
    if lo is not None and rating < lo:
        return False
    if hi is not None and rating > hi:
        return False
    return True


def _passes_year(
    ref: ExternalRef,
    item: MediaItem,
    lo: int | None,
    hi: int | None,
) -> bool:
    if lo is None and hi is None:
        return True
    year: int | None = None
    if item.release_date is not None:
        year = item.release_date.year
    elif ref.year is not None:
        year = ref.year
    if year is None:
        return False
    if lo is not None and year < lo:
        return False
    if hi is not None and year > hi:
        return False
    return True


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_str_set(value: Any) -> set[str]:
    if not value:
        return set()
    if isinstance(value, (str, bytes)):
        return {str(value)}
    if isinstance(value, (list, tuple, set)):
        return {str(v) for v in value if v is not None}
    return set()


def _as_lower_set(value: Any) -> set[str]:
    return {v.lower() for v in _as_str_set(value)}


# ---------------------------------------------------------------------------
# SQL translation (used by mass operations)
# ---------------------------------------------------------------------------


def apply_media_filters_to_query(
    stmt: Select,
    filters: dict[str, Any] | None,
) -> Select:
    """Translate the filter DSL to SQL ``WHERE`` clauses on ``MediaItem``.

    Only the keys that map cleanly to columns are honoured. Keys that
    require provider-level data (``min_rating`` / ``language``) are
    ignored here — mass operations only see local items.

    Supported keys:
      * ``media_type_in``           — list[str] (e.g. ["MOVIES", "SHOWS"])
      * ``min_year`` / ``max_year`` — int (from ``release_date``)
      * ``min_age`` / ``max_age``   — int
      * ``availability``            — list[str]
      * ``genre_in`` / ``genre_not_in`` — list[str], case-insensitive
      * ``require_files``           — bool, ``EXISTS`` on ``media_file``
    """
    if not filters:
        return stmt

    if media_types := _as_str_set(filters.get("media_type_in")):
        stmt = stmt.where(MediaItem.media_type.in_(media_types))
    if (min_year := _as_int(filters.get("min_year"))) is not None:
        stmt = stmt.where(
            extract("year", MediaItem.release_date) >= min_year
        )
    if (max_year := _as_int(filters.get("max_year"))) is not None:
        stmt = stmt.where(
            extract("year", MediaItem.release_date) <= max_year
        )
    if (min_age := _as_int(filters.get("min_age"))) is not None:
        stmt = stmt.where(MediaItem.min_age >= min_age)
    if (max_age := _as_int(filters.get("max_age"))) is not None:
        stmt = stmt.where(MediaItem.min_age <= max_age)
    if availability := _as_str_set(filters.get("availability")):
        stmt = stmt.where(MediaItem.availability_status.in_(availability))
    if genre_in := _as_lower_set(filters.get("genre_in")):
        # MediaItem has matching Genre via media_genre_table.
        sub = (
            select(media_genre_table.c.media_item_guid)
            .join(Genre, Genre.id == media_genre_table.c.genre_id)
            .where(func.lower(Genre.name).in_(genre_in))
        ).subquery()
        stmt = stmt.where(MediaItem.guid.in_(select(sub.c.media_item_guid)))
    if genre_not_in := _as_lower_set(filters.get("genre_not_in")):
        sub = (
            select(media_genre_table.c.media_item_guid)
            .join(Genre, Genre.id == media_genre_table.c.genre_id)
            .where(func.lower(Genre.name).in_(genre_not_in))
        ).subquery()
        stmt = stmt.where(MediaItem.guid.notin_(select(sub.c.media_item_guid)))
    if filters.get("require_files"):
        from pyrate.models.media import MediaFile

        stmt = stmt.where(
            exists().where(MediaFile.media_item_guid == MediaItem.guid)
        )
    return stmt
