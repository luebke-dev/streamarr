"""Convert all timestamp columns to timezone-aware

Revision ID: d5f6a7b8c9e0
Revises: c4e8f1a2b3d5
Create Date: 2026-03-12 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd5f6a7b8c9e0'
down_revision: Union[str, Sequence[str], None] = 'c4e8f1a2b3d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# All tables and their timestamp columns that need migration.
# Excludes 'libraries' and 'installed_plugins' (already migrated).
TABLES_COLUMNS: list[tuple[str, list[str]]] = [
    ("banners", ["start_date", "end_date", "created_at", "updated_at"]),
    ("user_banner_dismissed", ["dismissed_at"]),
    ("device", ["created_at", "updated_at", "last_activity", "playback_updated_at"]),
    ("downloader", ["created_at", "updated_at"]),
    ("download", ["created_at", "updated_at"]),
    ("favorite", ["created_at"]),
    ("friendship", ["created_at", "updated_at"]),
    ("genre", ["created_at", "updated_at"]),
    ("group", ["created_at", "updated_at"]),
    ("user_group_link", ["created_at"]),
    ("indexer", ["created_at", "updated_at"]),
    ("invite", ["created_at", "updated_at", "expires_at", "used_at"]),
    ("list", ["created_at", "updated_at", "last_auto_update"]),
    ("list_item", ["created_at"]),
    ("user_list_interaction", ["created_at"]),
    ("media_item", ["release_date", "created_at", "updated_at", "last_searched_at", "last_metadata_updated_at"]),
    ("media_file", ["created_at", "updated_at", "imported_at"]),
    ("media_release", ["created_at", "publish_date"]),
    ("media_release_link", ["created_at"]),
    ("media_external_id", ["created_at"]),
    ("media_genre", ["created_at"]),
    ("media_cast", ["created_at"]),
    ("notification", ["created_at", "updated_at", "read_at", "sent_at"]),
    ("person", ["created_at", "updated_at"]),
    ("settings", ["created_at", "updated_at"]),
    ("subscription_package", ["created_at", "updated_at"]),
    ("user_subscription", ["created_at", "updated_at", "starts_at", "expires_at", "cancelled_at"]),
    ("user_session", ["created_at", "updated_at", "last_activity"]),
    ("payment_history", ["created_at"]),
    ("user", ["created_at", "updated_at", "last_login"]),
    ("viewing_history", ["created_at", "updated_at", "last_watched_at", "first_watched_at"]),
    ("watch_party", ["created_at", "updated_at", "last_sync_at", "ended_at", "expires_at"]),
    ("watch_party_member", ["created_at", "updated_at", "last_heartbeat", "joined_at", "left_at"]),
]


def upgrade() -> None:
    """Convert all timestamp columns to TIMESTAMP WITH TIME ZONE."""
    for table, columns in TABLES_COLUMNS:
        for col in columns:
            op.execute(
                f'ALTER TABLE "{table}" '
                f'ALTER COLUMN "{col}" TYPE timestamp with time zone '
                f"USING \"{col}\" AT TIME ZONE 'UTC'"
            )


def downgrade() -> None:
    """Convert back to TIMESTAMP WITHOUT TIME ZONE."""
    for table, columns in TABLES_COLUMNS:
        for col in columns:
            op.execute(
                f'ALTER TABLE "{table}" '
                f'ALTER COLUMN "{col}" TYPE timestamp without time zone '
                f"USING \"{col}\" AT TIME ZONE 'UTC'"
            )
