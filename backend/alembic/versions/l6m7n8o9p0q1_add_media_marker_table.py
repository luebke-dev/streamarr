"""Add media_marker table for intro/outro/credits detection

Revision ID: l6m7n8o9p0q1
Revises: k5l6m7n8o9p0
Create Date: 2026-03-23

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "l6m7n8o9p0q1"
down_revision: str | None = "k5l6m7n8o9p0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "media_marker",
        sa.Column("guid", sa.Uuid(), nullable=False),
        sa.Column(
            "media_item_guid",
            sa.Uuid(),
            sa.ForeignKey("media_item.guid", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "marker_type",
            sa.Enum("intro", "outro", "credits", name="markertype"),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.Enum("manual", "chromaprint", "silence", name="markersource"),
            nullable=False,
            server_default="manual",
        ),
        sa.Column("start_seconds", sa.Float(), nullable=False),
        sa.Column("end_seconds", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("guid"),
        sa.UniqueConstraint(
            "media_item_guid",
            "marker_type",
            "source",
            name="uq_media_marker_item_type_source",
        ),
    )
    op.create_index("ix_media_marker_media_item_guid", "media_marker", ["media_item_guid"])
    op.create_index("ix_media_marker_marker_type", "media_marker", ["marker_type"])


def downgrade() -> None:
    op.drop_index("ix_media_marker_marker_type")
    op.drop_index("ix_media_marker_media_item_guid")
    op.drop_table("media_marker")
    op.execute("DROP TYPE IF EXISTS markertype")
    op.execute("DROP TYPE IF EXISTS markersource")
