"""split list.update_source unique into global vs per-user

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-04-26 16:30:00.000000

The old ``uq_list_system_update_source`` and the recently-added
``uq_list_update_source`` both treated ``update_source`` as globally
unique. That works for singleton system lists (``trending_movies``,
``trending_shows``) where ``owner_guid`` is NULL, but breaks per-user
system lists used by the recommendation engine — every user has their
own ``rec:for_you:movies`` row, so only the first user's rebuild
succeeded and every other user crashed with a UniqueViolationError.

Replace the single index with two scoped partial indexes:
- ``uq_list_global_update_source``: unique on ``update_source`` where
  ``owner_guid IS NULL`` (singleton lists like trending).
- ``uq_list_user_update_source``: unique on ``(owner_guid, update_source)``
  where ``owner_guid IS NOT NULL`` (per-user system lists like
  ``rec:for_you:*``).
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "d5e6f7a8b9c0"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_list_system_update_source")
    op.execute("DROP INDEX IF EXISTS uq_list_update_source")

    op.create_index(
        "uq_list_global_update_source",
        "list",
        ["update_source"],
        unique=True,
        postgresql_where="owner_guid IS NULL AND update_source IS NOT NULL",
    )
    op.create_index(
        "uq_list_user_update_source",
        "list",
        ["owner_guid", "update_source"],
        unique=True,
        postgresql_where="owner_guid IS NOT NULL AND update_source IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_index("uq_list_user_update_source", table_name="list")
    op.drop_index("uq_list_global_update_source", table_name="list")
    op.create_index(
        "uq_list_update_source",
        "list",
        ["update_source"],
        unique=True,
        postgresql_where="update_source IS NOT NULL",
    )
    op.create_index(
        "uq_list_system_update_source",
        "list",
        ["update_source"],
        unique=True,
        postgresql_where="list_type = 'SYSTEM' AND update_source IS NOT NULL",
    )
