"""add group and user_group_link tables

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-02-23

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f4a5b6c7d8e9"
down_revision = "e3f4a5b6c7d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "group",
        sa.Column("guid", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        # Library Access
        sa.Column("allowed_libraries", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        # Streaming
        sa.Column("max_concurrent_streams", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("max_game_streams", sa.Integer(), nullable=False, server_default="0"),
        # Download Permissions
        sa.Column("offline_download_limit", sa.Integer(), nullable=True),
        sa.Column("offline_download_period_minutes", sa.Integer(), nullable=False, server_default="1440"),
        # Prefetch
        sa.Column("prefetch_limit", sa.Integer(), nullable=True),
        sa.Column("prefetch_period_minutes", sa.Integer(), nullable=False, server_default="1440"),
        # On-demand fetch
        sa.Column("on_demand_fetch_limit", sa.Integer(), nullable=True),
        sa.Column("on_demand_fetch_period_minutes", sa.Integer(), nullable=False, server_default="1440"),
        # Quality
        sa.Column("max_video_quality", sa.String(), nullable=True, server_default="'uhd'"),
        sa.Column("max_audio_quality", sa.String(), nullable=True, server_default="'lossless'"),
        # Indexer
        sa.Column("indexer_api_requests_limit", sa.Integer(), nullable=True),
        sa.Column("indexer_api_requests_period_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("indexer_downloads_limit", sa.Integer(), nullable=True),
        sa.Column("indexer_downloads_period_minutes", sa.Integer(), nullable=False, server_default="1440"),
        # Playback
        sa.Column("playback_limit", sa.Integer(), nullable=True),
        sa.Column("playback_period_minutes", sa.Integer(), nullable=False, server_default="1440"),
        # Transcoding
        sa.Column("max_concurrent_transcodings", sa.Integer(), nullable=False, server_default="1"),
        sa.PrimaryKeyConstraint("guid"),
    )
    op.create_index(op.f("ix_group_name"), "group", ["name"], unique=True)

    op.create_table(
        "user_group_link",
        sa.Column("guid", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("group_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["user.guid"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["group_id"], ["group.guid"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("guid"),
    )
    op.create_index(op.f("ix_user_group_link_user_id"), "user_group_link", ["user_id"])
    op.create_index(op.f("ix_user_group_link_group_id"), "user_group_link", ["group_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_user_group_link_group_id"), table_name="user_group_link")
    op.drop_index(op.f("ix_user_group_link_user_id"), table_name="user_group_link")
    op.drop_table("user_group_link")
    op.drop_index(op.f("ix_group_name"), table_name="group")
    op.drop_table("group")
