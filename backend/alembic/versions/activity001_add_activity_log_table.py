"""Add activity_log table.

Revision ID: activity001
Revises: api_key001
Create Date: 2026-05-11 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "activity001"
down_revision: str | Sequence[str] | None = "api_key001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "activity_log",
        sa.Column("guid", sa.Uuid(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_guid", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("message", sa.String(length=1000), nullable=False),
        sa.Column("entity_type", sa.String(length=100), nullable=True),
        sa.Column("entity_guid", sa.Uuid(), nullable=True),
        sa.Column("extra_data", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["actor_guid"], ["user.guid"], ondelete="SET NULL"),
    )
    op.create_index(op.f("ix_activity_log_created_at"), "activity_log", ["created_at"])
    op.create_index(op.f("ix_activity_log_actor_guid"), "activity_log", ["actor_guid"])
    op.create_index(op.f("ix_activity_log_event_type"), "activity_log", ["event_type"])
    op.create_index(op.f("ix_activity_log_entity_type"), "activity_log", ["entity_type"])
    op.create_index(op.f("ix_activity_log_entity_guid"), "activity_log", ["entity_guid"])
    op.create_index(
        "ix_activity_log_entity",
        "activity_log",
        ["entity_type", "entity_guid"],
    )


def downgrade() -> None:
    op.drop_index("ix_activity_log_entity", table_name="activity_log")
    op.drop_index(op.f("ix_activity_log_entity_guid"), table_name="activity_log")
    op.drop_index(op.f("ix_activity_log_entity_type"), table_name="activity_log")
    op.drop_index(op.f("ix_activity_log_event_type"), table_name="activity_log")
    op.drop_index(op.f("ix_activity_log_actor_guid"), table_name="activity_log")
    op.drop_index(op.f("ix_activity_log_created_at"), table_name="activity_log")
    op.drop_table("activity_log")
