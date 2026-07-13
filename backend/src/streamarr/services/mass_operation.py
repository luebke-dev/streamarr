"""Bulk metadata operations over MediaItem rows.

A mass-operation rule defines:

  * ``target_filter`` — a filter-DSL dict selecting which MediaItems
    the action should touch.
  * ``action`` — a JSON object describing what to change. The supported
    types are intentionally narrow — they only mutate fields streamarr
    already models, and never introduce schema changes.

Actions
-------

* ``set_genre``       — replace or add to ``MediaItem.genres``.
    ``{"type": "set_genre", "values": ["Action", "Adventure"],
       "mode": "set" | "add"}``  (default ``set``)
* ``set_min_age``      — override parental ``min_age``.
    ``{"type": "set_min_age", "value": 12}``
* ``set_availability`` — override availability_status.
    ``{"type": "set_availability", "value": "available"}``
* ``set_description``  — override description.
    ``{"type": "set_description", "value": "…"}``
* ``set_poster_path``  — override poster URL.
    ``{"type": "set_poster_path", "value": "https://…"}``
* ``clear``            — set a single column to NULL.
    ``{"type": "clear", "field": "tagline"}``

Dry-run mode counts matches without persisting; the result row gets
``dry_run=True`` for audit traceability.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from streamarr.models.genre import Genre
from streamarr.models.mass_operation import (
    MassOperationRule,
    MassOperationRun,
    MassOperationRunStatus,
)
from streamarr.models.media import AvailabilityStatus, MediaItem
from streamarr.schemas.activity_log import ActivityLogCreate
from streamarr.services.activity_log import ActivityLogService
from streamarr.smart_collections.cron import next_run_after
from streamarr.smart_collections.filters import apply_media_filters_to_query

logger = logging.getLogger(__name__)


_CLEARABLE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "description",
        "tagline",
        "poster_path",
        "backdrop_path",
        "content_rating",
        "min_age",
    }
)


@dataclass(slots=True)
class MassOperationRunResult:
    rule_guid: uuid.UUID
    run_guid: uuid.UUID
    status: MassOperationRunStatus
    dry_run: bool
    items_matched: int = 0
    items_updated: int = 0
    items_skipped: int = 0
    duration_ms: int = 0
    error: str | None = None
    changed_sample: list[str] = None  # first ~20 changed media GUIDs

    def __post_init__(self):
        if self.changed_sample is None:
            self.changed_sample = []


class MassOperationError(Exception):
    """Raised when an action cannot be applied (validation failure)."""


class MassOperationService:
    """Execute one mass-operation rule end-to-end."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def run(
        self, rule_guid: uuid.UUID, *, dry_run: bool = False
    ) -> MassOperationRunResult:
        started_perf = time.perf_counter()
        rule = await self._get_rule(rule_guid)

        run_row = MassOperationRun(
            rule_guid=rule.guid,
            status=MassOperationRunStatus.RUNNING,
            started_at=datetime.now(UTC),
            dry_run=dry_run,
        )
        self.db.add(run_row)
        await self.db.commit()
        await self.db.refresh(run_row)

        result = MassOperationRunResult(
            rule_guid=rule.guid,
            run_guid=run_row.guid,
            status=MassOperationRunStatus.RUNNING,
            dry_run=dry_run,
        )

        try:
            self._validate_action(rule.action or {})
            items = await self._select_items(rule.target_filter or {})
            result.items_matched = len(items)

            if dry_run:
                # Count only — surface the first few GUIDs so the admin UI
                # can show "would touch these".
                result.changed_sample = [
                    str(item.guid) for item in items[:20]
                ]
                result.items_updated = len(items)
                result.status = MassOperationRunStatus.SUCCESS
            else:
                updated, skipped = await self._apply_action(
                    items, rule.action or {}
                )
                result.items_updated = updated
                result.items_skipped = skipped
                result.changed_sample = [str(item.guid) for item in items[:20]]
                result.status = MassOperationRunStatus.SUCCESS
                await self._audit(rule, result)

        except Exception as exc:  # noqa: BLE001
            logger.exception("mass-operation run failed: %s", exc)
            result.status = MassOperationRunStatus.FAILED
            result.error = str(exc)
            await self.db.rollback()
        finally:
            result.duration_ms = int(
                (time.perf_counter() - started_perf) * 1000
            )
            await self._finalize(rule, run_row, result)
        return result

    # ------------------------------------------------------------------
    # Pieces
    # ------------------------------------------------------------------

    async def _get_rule(self, rule_guid: uuid.UUID) -> MassOperationRule:
        rule = await self.db.get(MassOperationRule, rule_guid)
        if rule is None:
            raise LookupError(f"Mass-operation rule {rule_guid} not found")
        return rule

    async def _select_items(
        self, filters: dict[str, Any]
    ) -> list[MediaItem]:
        stmt = select(MediaItem).options(selectinload(MediaItem.genres))
        # Default: top-level items only (skip seasons/episodes).
        stmt = stmt.where(MediaItem.parent_guid.is_(None))
        stmt = apply_media_filters_to_query(stmt, filters)
        rows = (await self.db.execute(stmt)).scalars().unique().all()
        return list(rows)

    @staticmethod
    def _validate_action(action: dict[str, Any]) -> None:
        if not action:
            raise MassOperationError("Action is empty")
        kind = action.get("type")
        if kind == "set_genre":
            values = action.get("values")
            if not isinstance(values, list) or not values:
                raise MassOperationError(
                    "set_genre requires a non-empty 'values' list"
                )
            mode = action.get("mode", "set")
            if mode not in {"set", "add"}:
                raise MassOperationError(
                    f"set_genre mode must be 'set' or 'add', got {mode!r}"
                )
        elif kind == "set_min_age":
            if not isinstance(action.get("value"), int):
                raise MassOperationError("set_min_age requires an int 'value'")
        elif kind in {
            "set_availability",
            "set_description",
            "set_poster_path",
        }:
            value = action.get("value")
            if not isinstance(value, str) or not value:
                raise MassOperationError(
                    f"{kind} requires a non-empty string 'value'"
                )
            if kind == "set_availability":
                try:
                    AvailabilityStatus(value)
                except ValueError:
                    allowed = [status.value for status in AvailabilityStatus]
                    raise MassOperationError(
                        f"set_availability value {value!r} is not a valid "
                        f"availability status; allowed: {allowed}"
                    )
        elif kind == "clear":
            field_name = action.get("field")
            if field_name not in _CLEARABLE_FIELDS:
                raise MassOperationError(
                    f"clear: unsupported field {field_name!r}; "
                    f"allowed: {sorted(_CLEARABLE_FIELDS)}"
                )
        else:
            raise MassOperationError(f"Unknown action type {kind!r}")

    async def _apply_action(
        self,
        items: list[MediaItem],
        action: dict[str, Any],
    ) -> tuple[int, int]:
        """Apply ``action`` to all ``items``. Returns (updated, skipped)."""
        kind = action["type"]
        updated = 0
        skipped = 0

        if kind == "set_genre":
            genre_names = list(action["values"])
            mode = action.get("mode", "set")
            genres = await self._get_or_create_genres(genre_names)
            for item in items:
                current = {g.name.lower() for g in (item.genres or [])}
                new = {g.name.lower() for g in genres}
                if mode == "set":
                    if current == new:
                        skipped += 1
                        continue
                    item.genres = list(genres)
                    updated += 1
                else:  # add
                    missing = [g for g in genres if g.name.lower() not in current]
                    if not missing:
                        skipped += 1
                        continue
                    item.genres = [*(item.genres or []), *missing]
                    updated += 1
        elif kind == "set_min_age":
            value = int(action["value"])
            for item in items:
                if item.min_age == value:
                    skipped += 1
                    continue
                item.min_age = value
                updated += 1
        elif kind == "set_availability":
            value = AvailabilityStatus(action["value"])
            for item in items:
                current = item.availability_status
                if getattr(current, "value", current) == value.value:
                    skipped += 1
                    continue
                item.availability_status = value
                updated += 1
        elif kind == "set_description":
            value = action["value"]
            for item in items:
                if item.description == value:
                    skipped += 1
                    continue
                item.description = value
                updated += 1
        elif kind == "set_poster_path":
            value = action["value"]
            for item in items:
                if item.poster_path == value:
                    skipped += 1
                    continue
                item.poster_path = value
                updated += 1
        elif kind == "clear":
            field_name = action["field"]
            for item in items:
                if getattr(item, field_name) is None:
                    skipped += 1
                    continue
                setattr(item, field_name, None)
                updated += 1

        await self.db.commit()
        return updated, skipped

    async def _get_or_create_genres(
        self, names: list[str]
    ) -> list[Genre]:
        if not names:
            return []
        # Look up existing rows by case-insensitive name match.
        rows = (
            await self.db.execute(
                select(Genre).where(
                    Genre.name.in_(names)
                )
            )
        ).scalars().all()
        existing_by_lower = {g.name.lower(): g for g in rows}
        out: list[Genre] = []
        for name in names:
            existing = existing_by_lower.get(name.lower())
            if existing is not None:
                out.append(existing)
                continue
            new = Genre(name=name)
            self.db.add(new)
            out.append(new)
        await self.db.flush()
        return out

    async def _audit(
        self,
        rule: MassOperationRule,
        result: MassOperationRunResult,
    ) -> None:
        try:
            await ActivityLogService(self.db).create(
                ActivityLogCreate(
                    event_type="mass_operation.run",
                    message=(
                        f"Mass operation '{rule.name}' applied to "
                        f"{result.items_updated} item(s)"
                    ),
                    severity="info",
                ),
                actor_guid=None,
            )
        except Exception as exc:  # noqa: BLE001
            # Audit failure must never poison the operation.
            logger.warning("mass-operation audit log failed: %s", exc)

    async def _finalize(
        self,
        rule: MassOperationRule,
        run_row: MassOperationRun,
        result: MassOperationRunResult,
    ) -> None:
        run_row.status = result.status
        run_row.completed_at = datetime.now(UTC)
        run_row.duration_ms = result.duration_ms
        run_row.items_matched = result.items_matched
        run_row.items_updated = result.items_updated
        run_row.items_skipped = result.items_skipped
        run_row.error = result.error

        rule.last_run_at = datetime.now(UTC)
        rule.last_run_status = result.status
        rule.last_run_error = result.error
        if rule.schedule_cron:
            try:
                rule.next_run_at = next_run_after(rule.schedule_cron)
            except ValueError:
                rule.next_run_at = None
        else:
            rule.next_run_at = None

        await self.db.commit()
