"""Add page layout tables

Revision ID: f5a6b7c8d9e1
Revises: e6f7a8b9c0d1
Create Date: 2026-03-13 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f5a6b7c8d9e1'
down_revision: Union[str, Sequence[str], None] = 'e6f7a8b9c0d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create page_layout and page_section tables."""
    op.create_table(
        'page_layout',
        sa.Column('guid', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('slug', sa.String(), nullable=False),
        sa.Column('library_guid', sa.Uuid(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.ForeignKeyConstraint(['library_guid'], ['libraries.guid'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('guid'),
    )
    op.create_index(op.f('ix_page_layout_name'), 'page_layout', ['name'])
    op.create_index(op.f('ix_page_layout_slug'), 'page_layout', ['slug'], unique=True)
    op.create_index(op.f('ix_page_layout_library_guid'), 'page_layout', ['library_guid'])
    op.create_index(op.f('ix_page_layout_is_active'), 'page_layout', ['is_active'])

    op.create_table(
        'page_section',
        sa.Column('guid', sa.Uuid(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('layout_guid', sa.Uuid(), nullable=False),
        sa.Column('section_type', sa.String(), nullable=False),
        sa.Column('order_index', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('title', sa.String(), nullable=True),
        sa.Column('config', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('is_enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.ForeignKeyConstraint(['layout_guid'], ['page_layout.guid'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('guid'),
    )
    op.create_index(op.f('ix_page_section_layout_guid'), 'page_section', ['layout_guid'])
    op.create_index(op.f('ix_page_section_section_type'), 'page_section', ['section_type'])

    # Seed default "home" layout matching previous hard-coded behavior
    import uuid

    layout_guid = uuid.uuid4()
    op.execute(
        sa.text(
            "INSERT INTO page_layout (guid, name, slug, is_active) "
            "VALUES (:guid, :name, :slug, true)"
        ).bindparams(guid=layout_guid, name='Home', slug='home')
    )

    sections = [
        (uuid.uuid4(), layout_guid, 'hero_carousel', 0, 'Trending', '{}'),
        (uuid.uuid4(), layout_guid, 'continue_watching', 1, None, '{}'),
        (uuid.uuid4(), layout_guid, 'favorites', 2, None, '{}'),
        (uuid.uuid4(), layout_guid, 'all_genres', 3, None, '{"max_items_per_genre": 10}'),
    ]
    for s_guid, l_guid, s_type, order, title, config in sections:
        op.execute(
            sa.text(
                "INSERT INTO page_section (guid, layout_guid, section_type, order_index, title, config, is_enabled) "
                "VALUES (:guid, :layout_guid, :section_type, :order_index, :title, CAST(:cfg AS jsonb), true)"
            ).bindparams(
                guid=s_guid,
                layout_guid=l_guid,
                section_type=s_type,
                order_index=order,
                title=title,
                cfg=config,
            )
        )


def downgrade() -> None:
    """Drop page_section and page_layout tables."""
    op.drop_index(op.f('ix_page_section_section_type'), table_name='page_section')
    op.drop_index(op.f('ix_page_section_layout_guid'), table_name='page_section')
    op.drop_table('page_section')
    op.drop_index(op.f('ix_page_layout_is_active'), table_name='page_layout')
    op.drop_index(op.f('ix_page_layout_library_guid'), table_name='page_layout')
    op.drop_index(op.f('ix_page_layout_slug'), table_name='page_layout')
    op.drop_index(op.f('ix_page_layout_name'), table_name='page_layout')
    op.drop_table('page_layout')
