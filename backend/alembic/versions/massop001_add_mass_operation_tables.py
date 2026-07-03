"""add mass_operation_rule and mass_operation_run tables

Revision ID: massop001
Revises: overlay001
Create Date: 2026-05-14 12:10:00.000000

Introduces admin-defined bulk metadata operations (set_label, set_genre,
set_studio, set_rating_override, set_sort_title) that apply to all items
matching a filter. ``mass_operation_run`` is an audit trail with dry-run
support.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "massop001"
down_revision: str | Sequence[str] | None = "overlay001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mass_operation_rule",
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
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column(
            "target_filter",
            sa.JSON().with_variant(
                sa.dialects.postgresql.JSONB(), "postgresql"
            ),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "action",
            sa.JSON().with_variant(
                sa.dialects.postgresql.JSONB(), "postgresql"
            ),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("schedule_cron", sa.String(), nullable=True),
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
    )
    op.create_index(
        "ix_mass_operation_rule_name", "mass_operation_rule", ["name"]
    )
    op.create_index(
        "ix_mass_operation_rule_enabled",
        "mass_operation_rule",
        ["enabled"],
    )
    op.create_index(
        "ix_mass_operation_rule_is_system",
        "mass_operation_rule",
        ["is_system"],
    )
    op.create_index(
        "ix_mass_operation_rule_next_run_at",
        "mass_operation_rule",
        ["next_run_at"],
    )

    op.create_table(
        "mass_operation_run",
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
            "dry_run", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "items_matched", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "items_updated", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "items_skipped", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["rule_guid"],
            ["mass_operation_rule.guid"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_mass_operation_run_rule_guid",
        "mass_operation_run",
        ["rule_guid"],
    )
    op.create_index(
        "ix_mass_operation_run_status", "mass_operation_run", ["status"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_mass_operation_run_status", table_name="mass_operation_run"
    )
    op.drop_index(
        "ix_mass_operation_run_rule_guid", table_name="mass_operation_run"
    )
    op.drop_table("mass_operation_run")

    op.drop_index(
        "ix_mass_operation_rule_next_run_at",
        table_name="mass_operation_rule",
    )
    op.drop_index(
        "ix_mass_operation_rule_is_system",
        table_name="mass_operation_rule",
    )
    op.drop_index(
        "ix_mass_operation_rule_enabled",
        table_name="mass_operation_rule",
    )
    op.drop_index(
        "ix_mass_operation_rule_name", table_name="mass_operation_rule"
    )
    op.drop_table("mass_operation_rule")
