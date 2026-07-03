"""convert smart-collection / overlay / mass-operation columns to native pg enums

Revision ID: enumfix001
Revises: seeddef001
Create Date: 2026-05-14 17:00:00.000000

The original Phase A migrations created enum-backed columns as plain
``VARCHAR``. The SQLAlchemy models map them as ``Mapped[StrEnum]`` which
makes the asyncpg dialect emit ``$N::<enumname>`` casts in INSERT
statements at runtime, producing
``UndefinedObjectError: type "smartcollectionrunstatus" does not exist``.

Every existing StrEnum column in pyrate (listtype, mediatype, …) is
backed by a real PG ENUM, so we align the new tables with the
convention. Existing seeded values already match the enum members so
the in-place ``ALTER COLUMN … USING`` cast is safe.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "enumfix001"
down_revision: str | Sequence[str] | None = "seeddef001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (enum_type, members, table, column) tuples
_ENUM_COLUMNS = [
    (
        "smartcollectionmediatype",
        ("MOVIE", "SHOW"),
        "smart_collection_rule",
        "media_type",
    ),
    (
        "smartcollectionsyncmode",
        ("APPEND", "SYNC"),
        "smart_collection_rule",
        "sync_mode",
    ),
    (
        "smartcollectionrunstatus",
        ("PENDING", "RUNNING", "SUCCESS", "FAILED"),
        "smart_collection_rule",
        "last_run_status",
    ),
    (
        "smartcollectionrunstatus",
        ("PENDING", "RUNNING", "SUCCESS", "FAILED"),
        "smart_collection_run",
        "status",
    ),
    (
        "overlaymediascope",
        ("MOVIE", "SHOW", "BOTH"),
        "overlay_template",
        "media_scope",
    ),
    (
        "overlaytarget",
        ("POSTER", "BACKDROP"),
        "overlay_template",
        "target",
    ),
    (
        "overlaytarget",
        ("POSTER", "BACKDROP"),
        "overlay_application",
        "target",
    ),
    (
        "massoperationrunstatus",
        ("PENDING", "RUNNING", "SUCCESS", "FAILED"),
        "mass_operation_rule",
        "last_run_status",
    ),
    (
        "massoperationrunstatus",
        ("PENDING", "RUNNING", "SUCCESS", "FAILED"),
        "mass_operation_run",
        "status",
    ),
]


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Create the enum types once (idempotent guard for re-runs).
    seen: set[str] = set()
    for enum_type, members, _, _ in _ENUM_COLUMNS:
        if enum_type in seen:
            continue
        seen.add(enum_type)
        members_sql = ", ".join(f"'{m}'" for m in members)
        bind.execute(
            sa.text(
                f"DO $$ BEGIN "
                f"  CREATE TYPE {enum_type} AS ENUM ({members_sql}); "
                f"EXCEPTION WHEN duplicate_object THEN null; "
                f"END $$;"
            )
        )

    # 2. Postgres can't auto-cast a VARCHAR ``DEFAULT 'SYNC'`` to the new
    #    enum, so we drop the default first, ALTER the column, then set
    #    the default back as an enum literal in step 3.
    for _enum_type, _members, table, column in _ENUM_COLUMNS:
        bind.execute(
            sa.text(
                f"ALTER TABLE {table} ALTER COLUMN {column} DROP DEFAULT"
            )
        )
    for enum_type, _members, table, column in _ENUM_COLUMNS:
        bind.execute(
            sa.text(
                f"ALTER TABLE {table} "
                f"ALTER COLUMN {column} TYPE {enum_type} "
                f"USING {column}::{enum_type}"
            )
        )

    # 3. Drop the old server_default literals (e.g. 'SYNC', 'PENDING')
    #    and re-apply them as enum literals so future INSERTs without
    #    an explicit value resolve cleanly.
    _set_default("smart_collection_rule", "sync_mode", "SYNC", "smartcollectionsyncmode")
    _set_default("smart_collection_run", "status", "PENDING", "smartcollectionrunstatus")
    _set_default(
        "mass_operation_run", "status", "PENDING", "massoperationrunstatus"
    )


def downgrade() -> None:
    bind = op.get_bind()

    # Revert each column to TEXT and drop the enum types. We use TEXT
    # rather than VARCHAR to avoid forcing a length limit guess.
    for _enum_type, _members, table, column in _ENUM_COLUMNS:
        bind.execute(
            sa.text(
                f"ALTER TABLE {table} ALTER COLUMN {column} TYPE TEXT "
                f"USING {column}::text"
            )
        )

    seen: set[str] = set()
    for enum_type, _, _, _ in _ENUM_COLUMNS:
        if enum_type in seen:
            continue
        seen.add(enum_type)
        bind.execute(sa.text(f"DROP TYPE IF EXISTS {enum_type}"))

    # Restore the original VARCHAR-style server defaults.
    _set_default("smart_collection_rule", "sync_mode", "SYNC", None)
    _set_default("smart_collection_run", "status", "PENDING", None)
    _set_default("mass_operation_run", "status", "PENDING", None)


def _set_default(table: str, column: str, value: str, cast: str | None) -> None:
    bind = op.get_bind()
    if cast:
        bind.execute(
            sa.text(
                f"ALTER TABLE {table} ALTER COLUMN {column} "
                f"SET DEFAULT '{value}'::{cast}"
            )
        )
    else:
        bind.execute(
            sa.text(
                f"ALTER TABLE {table} ALTER COLUMN {column} SET DEFAULT '{value}'"
            )
        )
