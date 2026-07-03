"""partial unique index on list.update_source (also merges two open heads)

Revision ID: c4d5e6f7a8b9
Revises: voucher001, f5a6b7c8d9e1
Create Date: 2026-04-26 16:00:00.000000

The trending importer uses ``ON CONFLICT (update_source) DO NOTHING`` to
upsert system lists, but the column had no unique constraint, so PostgreSQL
rejected the statement with InvalidColumnReferenceError. All four trending
updaters were silently failing on every scheduled run. Add a partial unique
index that covers only rows with a non-NULL ``update_source`` so regular
user lists (NULL) keep working.

This migration also merges the two open heads ``voucher001`` and
``f5a6b7c8d9e1`` into a single linear history.
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "c4d5e6f7a8b9"
down_revision = ("voucher001", "f5a6b7c8d9e1")
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop any pre-existing duplicates so the index can be created.
    op.execute(
        """
        DELETE FROM list a
        USING list b
        WHERE a.guid > b.guid
          AND a.update_source IS NOT NULL
          AND a.update_source = b.update_source
        """
    )
    op.create_index(
        "uq_list_update_source",
        "list",
        ["update_source"],
        unique=True,
        postgresql_where="update_source IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_index("uq_list_update_source", table_name="list")
