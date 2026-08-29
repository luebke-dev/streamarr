"""Assign media files to their physical libraries.

Revision ID: libscan001
Revises: authtva001
Create Date: 2026-08-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "libscan001"
down_revision: str | Sequence[str] | None = "authtva001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "media_file",
        sa.Column("library_guid", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_media_file_library_guid",
        "media_file",
        ["library_guid"],
    )
    op.create_foreign_key(
        "fk_media_file_library_guid",
        "media_file",
        "libraries",
        ["library_guid"],
        ["guid"],
        ondelete="SET NULL",
    )

    # Existing local files can be assigned safely by longest matching root.
    # Remote/rclone files intentionally remain NULL.
    op.execute(
        sa.text(
            """
            UPDATE media_file AS mf
            SET library_guid = (
                SELECT l.guid
                FROM libraries AS l
                WHERE mf.file_path = rtrim(l.path, '/')
                   OR mf.file_path LIKE rtrim(l.path, '/') || '/%'
                ORDER BY length(rtrim(l.path, '/')) DESC
                LIMIT 1
            )
            WHERE mf.library_guid IS NULL
              AND EXISTS (
                  SELECT 1
                  FROM libraries AS l
                  WHERE mf.file_path = rtrim(l.path, '/')
                     OR mf.file_path LIKE rtrim(l.path, '/') || '/%'
              )
            """
        )
    )


def downgrade() -> None:
    op.drop_constraint("fk_media_file_library_guid", "media_file", type_="foreignkey")
    op.drop_index("ix_media_file_library_guid", table_name="media_file")
    op.drop_column("media_file", "library_guid")
