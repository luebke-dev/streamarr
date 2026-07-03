"""add quality tracking to media_file

Revision ID: qualprof001
Revises: favmon001
Create Date: 2026-05-16 17:31:00.000000

Links a MediaFile back to the MediaRelease it was imported from and stores
the parsed quality ladder rank + additive score, so upgrade decisions can
compare the current file against a candidate release without re-deriving
quality from probe data. Best-effort backfill via the existing
Download -> MediaReleaseLink -> MediaRelease chain.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "qualprof001"
down_revision: str | Sequence[str] | None = "favmon001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "media_file",
        sa.Column("source_release_guid", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "media_file", sa.Column("quality_rank", sa.Integer(), nullable=True)
    )
    op.add_column(
        "media_file", sa.Column("quality_score", sa.Float(), nullable=True)
    )
    op.create_index(
        "ix_media_file_source_release_guid",
        "media_file",
        ["source_release_guid"],
    )
    op.create_foreign_key(
        "fk_media_file_source_release_guid",
        "media_file",
        "media_release",
        ["source_release_guid"],
        ["guid"],
        ondelete="SET NULL",
    )

    # Best-effort: link each media_file to the release of the most recent
    # imported download for the same media item.
    op.execute(
        sa.text(
            """
            UPDATE media_file mf
            SET source_release_guid = sub.media_release_guid
            FROM (
                SELECT DISTINCT ON (mr.media_item_guid)
                       mr.media_item_guid,
                       mr.guid AS media_release_guid
                FROM download d
                JOIN media_release_link mrl
                  ON mrl.guid = d.media_release_link_guid
                JOIN media_release mr
                  ON mr.guid = mrl.media_release_guid
                WHERE d.status = 'Imported'
                ORDER BY mr.media_item_guid, d.updated_at DESC
            ) sub
            WHERE mf.media_item_guid = sub.media_item_guid
              AND mf.source_release_guid IS NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_media_file_source_release_guid", "media_file", type_="foreignkey"
    )
    op.drop_index(
        "ix_media_file_source_release_guid", table_name="media_file"
    )
    op.drop_column("media_file", "quality_score")
    op.drop_column("media_file", "quality_rank")
    op.drop_column("media_file", "source_release_guid")
