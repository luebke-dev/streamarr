"""Add multi-root and stable identity fields to media files.

Revision ID: libscan002
Revises: libscan001
Create Date: 2026-08-24
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "libscan002"
down_revision: str | Sequence[str] | None = "libscan001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("media_file", sa.Column("library_root", sa.String(), nullable=True))
    op.add_column(
        "media_file", sa.Column("filesystem_device", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "media_file", sa.Column("filesystem_inode", sa.BigInteger(), nullable=True)
    )
    op.add_column("media_file", sa.Column("modified_ns", sa.BigInteger(), nullable=True))
    op.add_column("media_file", sa.Column("identity_key", sa.String(), nullable=True))
    op.add_column("media_file", sa.Column("last_seen_scan_id", sa.Uuid(), nullable=True))
    op.create_index("ix_media_file_library_root", "media_file", ["library_root"])
    op.create_index("ix_media_file_identity_key", "media_file", ["identity_key"])
    op.create_index("ix_media_file_last_seen_scan_id", "media_file", ["last_seen_scan_id"])
    op.create_index(
        "ix_media_file_library_identity",
        "media_file",
        ["library_guid", "identity_key"],
    )
    op.execute(
        sa.text(
            """
            UPDATE media_file AS mf
            SET library_root = (
                SELECT rtrim(l.path, '/')
                FROM libraries AS l
                WHERE l.guid = mf.library_guid
                  AND (mf.file_path = rtrim(l.path, '/')
                       OR mf.file_path LIKE rtrim(l.path, '/') || '/%')
                LIMIT 1
            )
            WHERE mf.library_guid IS NOT NULL
              AND mf.library_root IS NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_media_file_library_identity", table_name="media_file")
    op.drop_index("ix_media_file_last_seen_scan_id", table_name="media_file")
    op.drop_index("ix_media_file_identity_key", table_name="media_file")
    op.drop_index("ix_media_file_library_root", table_name="media_file")
    op.drop_column("media_file", "last_seen_scan_id")
    op.drop_column("media_file", "identity_key")
    op.drop_column("media_file", "modified_ns")
    op.drop_column("media_file", "filesystem_inode")
    op.drop_column("media_file", "filesystem_device")
    op.drop_column("media_file", "library_root")
