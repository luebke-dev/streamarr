"""End-to-end orchestration of a smart-collection rule run."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.metadata.list_sources import ListSourceMediaType
from pyrate.models.list import List, ListType, ListVisibility
from pyrate.models.smart_collection import (
    SmartCollectionMediaType,
    SmartCollectionRule,
    SmartCollectionRun,
    SmartCollectionRunStatus,
    SmartCollectionSyncMode,
)
from pyrate.services.list import ListService
from pyrate.smart_collections.builders import build_builder
from pyrate.smart_collections.cron import next_run_after
from pyrate.smart_collections.filters import filter_resolved
from pyrate.smart_collections.resolver import RefResolver

logger = logging.getLogger(__name__)


_MEDIA_TYPE_BRIDGE = {
    SmartCollectionMediaType.MOVIE: ListSourceMediaType.MOVIE,
    SmartCollectionMediaType.SHOW: ListSourceMediaType.SHOW,
}
_LIST_ITEM_TYPE = {
    SmartCollectionMediaType.MOVIE: "MOVIE",
    SmartCollectionMediaType.SHOW: "SHOW",
}


@dataclass(slots=True)
class SmartCollectionRunResult:
    rule_guid: uuid.UUID
    run_guid: uuid.UUID
    status: SmartCollectionRunStatus
    items_fetched: int = 0
    items_filtered: int = 0
    items_resolved: int = 0
    items_added: int = 0
    items_removed: int = 0
    items_unresolved: int = 0
    duration_ms: int = 0
    error: str | None = None
    debug: dict[str, Any] = field(default_factory=dict)


class SmartCollectionService:
    """Run a single smart-collection rule end-to-end.

    Lifecycle of one ``run(rule_guid)`` call:
      1. Load rule. Bail out if disabled.
      2. Construct builder via ``build_builder``.
      3. ``builder.fetch`` → ``ExternalRef`` list.
      4. ``RefResolver.resolve`` → (ref, MediaItem) pairs.
      5. ``filter_resolved`` applies rule.filters.
      6. Ensure target ``List`` exists; populate via ``ListService``.
      7. Persist ``SmartCollectionRun`` and update rule cursor fields.
    """

    def __init__(
        self,
        db: AsyncSession,
        *,
        api_keys: dict[str, Any] | None = None,
    ) -> None:
        self.db = db
        self.api_keys = api_keys or {}

    async def run(self, rule_guid: uuid.UUID) -> SmartCollectionRunResult:
        started_at = datetime.now(UTC)
        started_perf = time.perf_counter()

        rule = await self._get_rule(rule_guid)
        run_row = SmartCollectionRun(
            rule_guid=rule.guid,
            status=SmartCollectionRunStatus.RUNNING,
            started_at=started_at,
        )
        self.db.add(run_row)
        await self.db.commit()
        await self.db.refresh(run_row)

        result = SmartCollectionRunResult(
            rule_guid=rule.guid,
            run_guid=run_row.guid,
            status=SmartCollectionRunStatus.RUNNING,
        )

        try:
            list_source_media_type = _MEDIA_TYPE_BRIDGE[rule.media_type]
            list_item_type = _LIST_ITEM_TYPE[rule.media_type]
            limit = rule.item_limit

            builder = build_builder(rule.builder_type, self.api_keys)
            try:
                build_result = await builder.fetch(
                    rule.builder_config or {},
                    media_type=list_source_media_type,
                    limit=limit,
                    db=self.db,
                )
            finally:
                await builder.close()

            result.items_fetched = len(build_result.refs)
            result.debug = dict(build_result.debug)

            resolver = RefResolver(self.db)
            resolve = await resolver.resolve(
                build_result.refs, media_type=list_source_media_type
            )
            result.items_resolved = len(resolve.resolved)
            result.items_unresolved = len(resolve.unresolved)

            filtered = filter_resolved(resolve.resolved, rule.filters)
            result.items_filtered = len(filtered)

            target_list = await self._ensure_target_list(rule)

            previous_item_count = target_list.item_count or 0
            result.items_added = await self._apply_to_list(
                target_list, filtered, list_item_type, rule.sync_mode
            )
            if rule.sync_mode == SmartCollectionSyncMode.SYNC:
                result.items_removed = max(
                    0, previous_item_count - len(filtered)
                )

            result.status = SmartCollectionRunStatus.SUCCESS

        except Exception as exc:  # noqa: BLE001 — record any failure
            logger.exception("smart-collection run failed: %s", exc)
            result.status = SmartCollectionRunStatus.FAILED
            result.error = str(exc)
            await self.db.rollback()
        finally:
            result.duration_ms = int(
                (time.perf_counter() - started_perf) * 1000
            )
            await self._finalize(rule, run_row, result)
        return result

    # ------------------------------------------------------------------

    async def _get_rule(self, rule_guid: uuid.UUID) -> SmartCollectionRule:
        rule = await self.db.get(SmartCollectionRule, rule_guid)
        if rule is None:
            raise LookupError(f"Smart-collection rule {rule_guid} not found")
        return rule

    async def _ensure_target_list(
        self, rule: SmartCollectionRule
    ) -> List:
        if rule.list_guid is not None:
            target = await self.db.get(List, rule.list_guid)
            if target is not None:
                if target.name != rule.name:
                    target.name = rule.name
                if target.description != rule.description:
                    target.description = rule.description
                target.auto_update = True
                target.last_auto_update = datetime.now(UTC)
                return target
        # Create a fresh SYSTEM list bound to this rule.
        target = List(
            name=rule.name,
            description=rule.description,
            list_type=ListType.SYSTEM,
            visibility=ListVisibility.PUBLIC,
            auto_update=True,
            update_source=f"smart:{rule.guid}",
            last_auto_update=datetime.now(UTC),
            is_active=True,
        )
        self.db.add(target)
        await self.db.flush()
        rule.list_guid = target.guid
        return target

    async def _apply_to_list(
        self,
        target_list: List,
        filtered: list,
        list_item_type: str,
        sync_mode: SmartCollectionSyncMode,
    ) -> int:
        from pyrate.models.list import ListItem

        list_service = ListService(self.db)
        items = [
            (item.guid, list_item_type, order)
            for order, (_, item) in enumerate(filtered)
        ]
        if sync_mode == SmartCollectionSyncMode.SYNC:
            await list_service.replace_items(target_list.guid, items)
            return len(items)
        # APPEND: add any items that are not already present.
        existing_result = await self.db.execute(
            select(ListItem.item_guid).where(
                ListItem.list_guid == target_list.guid
            )
        )
        existing_guids = set(existing_result.scalars().all())

        order_start = target_list.item_count or 0
        added = 0
        for item_guid, type_token, _ in items:
            if item_guid in existing_guids:
                continue
            self.db.add(
                ListItem(
                    list_guid=target_list.guid,
                    item_type=type_token,
                    item_guid=item_guid,
                    order_index=order_start + added,
                )
            )
            existing_guids.add(item_guid)
            added += 1
        target_list.item_count = order_start + added
        target_list.last_auto_update = datetime.now(UTC)
        await self.db.commit()
        return added

    async def _finalize(
        self,
        rule: SmartCollectionRule,
        run_row: SmartCollectionRun,
        result: SmartCollectionRunResult,
    ) -> None:
        run_row.status = result.status
        run_row.completed_at = datetime.now(UTC)
        run_row.duration_ms = result.duration_ms
        run_row.items_fetched = result.items_fetched
        run_row.items_filtered = result.items_filtered
        run_row.items_resolved = result.items_resolved
        run_row.items_added = result.items_added
        run_row.items_removed = result.items_removed
        run_row.items_unresolved = result.items_unresolved
        run_row.error = result.error

        rule.last_run_at = datetime.now(UTC)
        rule.last_run_status = result.status
        rule.last_run_error = result.error
        try:
            rule.next_run_at = next_run_after(rule.schedule_cron)
        except ValueError as exc:
            logger.warning(
                "smart-collection %s: invalid cron %s — clearing next_run_at: %s",
                rule.guid,
                rule.schedule_cron,
                exc,
            )
            rule.next_run_at = None

        await self.db.commit()
