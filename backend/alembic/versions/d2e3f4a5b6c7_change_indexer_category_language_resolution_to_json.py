"""change indexer_category language and resolution to JSON arrays

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-02-18

"""

from alembic import op
import sqlalchemy as sa

revision = 'd2e3f4a5b6c7'
down_revision = 'c1d2e3f4a5b6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Convert existing string values to JSON arrays, then change column type
    op.execute("""
        UPDATE indexer_category
        SET language = to_json(ARRAY[language])
        WHERE language IS NOT NULL AND language != 'null'
    """)
    op.execute("""
        UPDATE indexer_category
        SET resolution = to_json(ARRAY[resolution])
        WHERE resolution IS NOT NULL AND resolution != 'null'
    """)

    op.alter_column(
        'indexer_category',
        'language',
        existing_type=sa.String(),
        type_=sa.JSON(),
        existing_nullable=True,
        postgresql_using='language::json',
    )
    op.alter_column(
        'indexer_category',
        'resolution',
        existing_type=sa.String(),
        type_=sa.JSON(),
        existing_nullable=True,
        postgresql_using='resolution::json',
    )


def downgrade() -> None:
    op.alter_column(
        'indexer_category',
        'language',
        existing_type=sa.JSON(),
        type_=sa.String(),
        existing_nullable=True,
        postgresql_using="language->>0",
    )
    op.alter_column(
        'indexer_category',
        'resolution',
        existing_type=sa.JSON(),
        type_=sa.String(),
        existing_nullable=True,
        postgresql_using="resolution->>0",
    )
