"""Add deduplicating unique constraints

Revision ID: uniqcon001
Revises: slugspd001
Create Date: 2026-07-03 00:00:00.000000

Adds idempotency-guarding unique constraints on list_item, viewing_history,
favorites lists, media_external_id and active downloads. Existing duplicate
rows are removed first (keeping the oldest, or for viewing_history the most
recently watched entry) so the constraints can be created cleanly.
"""

from alembic import op

revision = "uniqcon001"
down_revision = "slugspd001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM list_item a USING list_item b
        WHERE a.list_guid = b.list_guid
          AND a.item_guid = b.item_guid
          AND a.item_type = b.item_type
          AND (a.created_at > b.created_at
               OR (a.created_at = b.created_at AND a.ctid > b.ctid))
        """
    )
    op.create_unique_constraint(
        "uq_list_item_list_item_type",
        "list_item",
        ["list_guid", "item_guid", "item_type"],
    )

    op.execute(
        """
        DELETE FROM viewing_history a USING viewing_history b
        WHERE a.user_guid = b.user_guid
          AND a.media_item_guid = b.media_item_guid
          AND (a.last_watched_at < b.last_watched_at
               OR (a.last_watched_at = b.last_watched_at AND a.ctid > b.ctid))
        """
    )
    op.create_unique_constraint(
        "uq_viewing_history_user_item",
        "viewing_history",
        ["user_guid", "media_item_guid"],
    )

    op.execute(
        """
        DELETE FROM list a USING list b
        WHERE a.list_type = 'FAVORITES'
          AND b.list_type = 'FAVORITES'
          AND a.owner_guid = b.owner_guid
          AND (a.created_at > b.created_at
               OR (a.created_at = b.created_at AND a.ctid > b.ctid))
        """
    )
    op.create_index(
        "uq_list_favorites_owner",
        "list",
        ["owner_guid"],
        unique=True,
        postgresql_where="list_type = 'FAVORITES'",
    )

    op.execute(
        """
        DELETE FROM media_external_id a USING media_external_id b
        WHERE a.provider = b.provider
          AND a.external_id = b.external_id
          AND (a.created_at > b.created_at
               OR (a.created_at = b.created_at AND a.ctid > b.ctid))
        """
    )
    op.create_unique_constraint(
        "uq_media_external_id_provider_external",
        "media_external_id",
        ["provider", "external_id"],
    )

    op.execute(
        """
        DELETE FROM download a USING download b
        WHERE a.media_release_link_guid = b.media_release_link_guid
          AND a.media_release_link_guid IS NOT NULL
          AND a.status NOT IN ('Failed', 'Imported', 'Completed')
          AND b.status NOT IN ('Failed', 'Imported', 'Completed')
          AND (a.created_at < b.created_at
               OR (a.created_at = b.created_at AND a.ctid > b.ctid))
        """
    )
    op.create_index(
        "uq_download_active_release_link",
        "download",
        ["media_release_link_guid"],
        unique=True,
        postgresql_where=(
            "media_release_link_guid IS NOT NULL "
            "AND status NOT IN ('Failed', 'Imported', 'Completed')"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_download_active_release_link", table_name="download")
    op.drop_constraint(
        "uq_media_external_id_provider_external",
        "media_external_id",
        type_="unique",
    )
    op.drop_index("uq_list_favorites_owner", table_name="list")
    op.drop_constraint(
        "uq_viewing_history_user_item", "viewing_history", type_="unique"
    )
    op.drop_constraint("uq_list_item_list_item_type", "list_item", type_="unique")
