"""add smart_collection_rule and smart_collection_run tables

Revision ID: smartcoll001
Revises: trailersection001
Create Date: 2026-05-14 12:00:00.000000

Introduces auto-populating "smart collections": admin-defined rules that
fetch items from external sources (TMDb charts, Trakt lists, IMDb, etc.),
filter them, and sync them into a target ``list`` on a cron schedule.
``smart_collection_run`` is a per-execution audit trail with metrics.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "smartcoll001"
down_revision: str | Sequence[str] | None = "trailersection001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "smart_collection_rule",
        sa.Column(
            "guid",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("list_guid", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("media_type", sa.String(), nullable=False),
        sa.Column("builder_type", sa.String(), nullable=False),
        sa.Column(
            "builder_config",
            sa.JSON().with_variant(
                sa.dialects.postgresql.JSONB(), "postgresql"
            ),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "filters",
            sa.JSON().with_variant(
                sa.dialects.postgresql.JSONB(), "postgresql"
            ),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "sync_mode", sa.String(), nullable=False, server_default="SYNC"
        ),
        sa.Column("item_limit", sa.Integer(), nullable=True),
        sa.Column("schedule_cron", sa.String(), nullable=False),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "is_system",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("next_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_run_status", sa.String(), nullable=True),
        sa.Column("last_run_error", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["list_guid"], ["list.guid"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("list_guid", name="uq_smart_collection_rule_list"),
    )
    op.create_index(
        "ix_smart_collection_rule_name", "smart_collection_rule", ["name"]
    )
    op.create_index(
        "ix_smart_collection_rule_media_type",
        "smart_collection_rule",
        ["media_type"],
    )
    op.create_index(
        "ix_smart_collection_rule_builder_type",
        "smart_collection_rule",
        ["builder_type"],
    )
    op.create_index(
        "ix_smart_collection_rule_enabled",
        "smart_collection_rule",
        ["enabled"],
    )
    op.create_index(
        "ix_smart_collection_rule_is_system",
        "smart_collection_rule",
        ["is_system"],
    )
    op.create_index(
        "ix_smart_collection_rule_next_run_at",
        "smart_collection_rule",
        ["next_run_at"],
    )
    op.create_index(
        "ix_smart_collection_rule_enabled_next",
        "smart_collection_rule",
        ["enabled", "next_run_at"],
    )

    op.create_table(
        "smart_collection_run",
        sa.Column(
            "guid",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("rule_guid", sa.Uuid(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column(
            "status", sa.String(), nullable=False, server_default="PENDING"
        ),
        sa.Column(
            "items_fetched", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "items_filtered", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "items_resolved", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "items_added", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "items_removed", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "items_unresolved",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["rule_guid"],
            ["smart_collection_rule.guid"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_smart_collection_run_rule_guid",
        "smart_collection_run",
        ["rule_guid"],
    )
    op.create_index(
        "ix_smart_collection_run_status",
        "smart_collection_run",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_smart_collection_run_status", table_name="smart_collection_run"
    )
    op.drop_index(
        "ix_smart_collection_run_rule_guid", table_name="smart_collection_run"
    )
    op.drop_table("smart_collection_run")

    op.drop_index(
        "ix_smart_collection_rule_enabled_next",
        table_name="smart_collection_rule",
    )
    op.drop_index(
        "ix_smart_collection_rule_next_run_at",
        table_name="smart_collection_rule",
    )
    op.drop_index(
        "ix_smart_collection_rule_is_system",
        table_name="smart_collection_rule",
    )
    op.drop_index(
        "ix_smart_collection_rule_enabled",
        table_name="smart_collection_rule",
    )
    op.drop_index(
        "ix_smart_collection_rule_builder_type",
        table_name="smart_collection_rule",
    )
    op.drop_index(
        "ix_smart_collection_rule_media_type",
        table_name="smart_collection_rule",
    )
    op.drop_index(
        "ix_smart_collection_rule_name", table_name="smart_collection_rule"
    )
    op.drop_table("smart_collection_rule")
