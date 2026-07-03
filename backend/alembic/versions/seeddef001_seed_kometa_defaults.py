"""seed kometa-style default smart-collection rules and overlay templates

Revision ID: seeddef001
Revises: massop001
Create Date: 2026-05-14 12:15:00.000000

Inserts ~50 ``SmartCollectionRule`` rows and ~5 ``OverlayTemplate``
rows as ``is_system=True, enabled=False`` so a fresh install ships
useful out-of-the-box defaults without immediately hammering external
APIs. Admins flip the ones they want in the admin UI.

The actual content lives in :mod:`pyrate.smart_collections.defaults`
so it can be tested independently and re-used by the bulk-enable
helper in the worker module.

Both inserts use ``ON CONFLICT DO NOTHING`` on the primary key (every
default carries a deterministic UUID derived from its slug), so this
migration is safe to re-run.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert

from alembic import op

revision: str = "seeddef001"
down_revision: str | Sequence[str] | None = "massop001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_RULES_INSERT = sa.text(
    """
    INSERT INTO smart_collection_rule (
        guid, name, description, media_type, builder_type,
        builder_config, filters, sync_mode, item_limit, schedule_cron,
        enabled, is_system, created_at, updated_at
    )
    VALUES (
        :guid, :name, :description, :media_type, :builder_type,
        CAST(:builder_config AS JSONB), CAST(:filters AS JSONB),
        :sync_mode, :item_limit, :schedule_cron,
        :enabled, true, NOW(), NOW()
    )
    ON CONFLICT (guid) DO NOTHING
    """
)

_OVERLAYS_INSERT = sa.text(
    """
    INSERT INTO overlay_template (
        guid, name, description, media_scope, target,
        condition, elements, z_order, enabled, is_system, version,
        created_at, updated_at
    )
    VALUES (
        :guid, :name, :description, :media_scope, :target,
        CAST(:condition AS JSONB), CAST(:elements AS JSONB),
        :z_order, :enabled, true, 1, NOW(), NOW()
    )
    ON CONFLICT (guid) DO NOTHING
    """
)


def upgrade() -> None:
    # Import lazily so the migration module stays importable even when
    # the application package has changed shape between revisions.
    from pyrate.smart_collections.defaults import (
        OVERLAY_DEFAULTS,
        SMART_COLLECTION_DEFAULTS,
    )

    bind = op.get_bind()
    for entry in SMART_COLLECTION_DEFAULTS:
        bind.execute(
            _RULES_INSERT,
            {
                "guid": entry["guid"],
                "name": entry["name"],
                "description": entry.get("description"),
                "media_type": entry["media_type"],
                "builder_type": entry["builder_type"],
                "builder_config": json.dumps(entry.get("builder_config") or {}),
                "filters": json.dumps(entry.get("filters") or {}),
                "sync_mode": entry.get("sync_mode", "SYNC"),
                "item_limit": entry.get("item_limit"),
                "schedule_cron": entry["schedule_cron"],
                "enabled": False,
            },
        )
    for entry in OVERLAY_DEFAULTS:
        bind.execute(
            _OVERLAYS_INSERT,
            {
                "guid": entry["guid"],
                "name": entry["name"],
                "description": entry.get("description"),
                "media_scope": entry.get("media_scope", "BOTH"),
                "target": entry.get("target", "POSTER"),
                "condition": json.dumps(entry.get("condition") or None)
                if entry.get("condition") is not None
                else None,
                "elements": json.dumps(entry.get("elements") or []),
                "z_order": entry.get("z_order", 0),
                "enabled": False,
            },
        )


def downgrade() -> None:
    from pyrate.smart_collections.defaults import (
        OVERLAY_DEFAULTS,
        SMART_COLLECTION_DEFAULTS,
    )

    bind = op.get_bind()
    rule_guids = [entry["guid"] for entry in SMART_COLLECTION_DEFAULTS]
    overlay_guids = [entry["guid"] for entry in OVERLAY_DEFAULTS]
    if rule_guids:
        bind.execute(
            sa.text(
                "DELETE FROM smart_collection_rule "
                "WHERE guid = ANY(:guids) AND is_system = true"
            ),
            {"guids": rule_guids},
        )
    if overlay_guids:
        bind.execute(
            sa.text(
                "DELETE FROM overlay_template "
                "WHERE guid = ANY(:guids) AND is_system = true"
            ),
            {"guids": overlay_guids},
        )
