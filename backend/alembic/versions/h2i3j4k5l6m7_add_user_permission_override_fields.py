"""add user permission override fields

Revision ID: h2i3j4k5l6m7
Revises: g1h2i3j4k5l6
Create Date: 2026-03-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "h2i3j4k5l6m7"
down_revision: str | None = "g1h2i3j4k5l6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Permission override fields (all nullable — None = inherit from group/global)
    op.add_column("user", sa.Column("allowed_libraries", postgresql.JSONB(), nullable=True))
    op.add_column("user", sa.Column("max_concurrent_streams", sa.Integer(), nullable=True))
    op.add_column("user", sa.Column("max_game_streams", sa.Integer(), nullable=True))
    op.add_column("user", sa.Column("max_video_quality", sa.String(), nullable=True))
    op.add_column("user", sa.Column("max_audio_quality", sa.String(), nullable=True))
    op.add_column("user", sa.Column("max_concurrent_transcodings", sa.Integer(), nullable=True))
    op.add_column("user", sa.Column("offline_download_limit", sa.Integer(), nullable=True))
    op.add_column("user", sa.Column("offline_download_period_minutes", sa.Integer(), nullable=True))
    op.add_column("user", sa.Column("prefetch_limit", sa.Integer(), nullable=True))
    op.add_column("user", sa.Column("prefetch_period_minutes", sa.Integer(), nullable=True))
    op.add_column("user", sa.Column("on_demand_fetch_limit", sa.Integer(), nullable=True))
    op.add_column("user", sa.Column("on_demand_fetch_period_minutes", sa.Integer(), nullable=True))
    op.add_column("user", sa.Column("indexer_api_requests_limit", sa.Integer(), nullable=True))
    op.add_column("user", sa.Column("indexer_api_requests_period_minutes", sa.Integer(), nullable=True))
    op.add_column("user", sa.Column("indexer_downloads_limit", sa.Integer(), nullable=True))
    op.add_column("user", sa.Column("indexer_downloads_period_minutes", sa.Integer(), nullable=True))
    op.add_column("user", sa.Column("playback_limit", sa.Integer(), nullable=True))
    op.add_column("user", sa.Column("playback_period_minutes", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("user", "playback_period_minutes")
    op.drop_column("user", "playback_limit")
    op.drop_column("user", "indexer_downloads_period_minutes")
    op.drop_column("user", "indexer_downloads_limit")
    op.drop_column("user", "indexer_api_requests_period_minutes")
    op.drop_column("user", "indexer_api_requests_limit")
    op.drop_column("user", "on_demand_fetch_period_minutes")
    op.drop_column("user", "on_demand_fetch_limit")
    op.drop_column("user", "prefetch_period_minutes")
    op.drop_column("user", "prefetch_limit")
    op.drop_column("user", "offline_download_period_minutes")
    op.drop_column("user", "offline_download_limit")
    op.drop_column("user", "max_concurrent_transcodings")
    op.drop_column("user", "max_audio_quality")
    op.drop_column("user", "max_video_quality")
    op.drop_column("user", "max_game_streams")
    op.drop_column("user", "max_concurrent_streams")
    op.drop_column("user", "allowed_libraries")
