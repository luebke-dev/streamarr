"""add container_profile table and seed builtin steam profile

Revision ID: ctnprof001
Revises: xdat29fav210
Create Date: 2026-07-04 00:00:00.000000

Introduces the global ``container_profile`` table backing generic
"container profiles" (game = container, GOW-agnostic) and seeds a single
builtin ``steam`` profile so existing Steam launch behaviour is preserved
by default (image + runtime_profile unchanged).

The seed is idempotent: it only inserts the ``steam`` profile when no row
with that name already exists, so the migration is safe to re-run.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "ctnprof001"
down_revision: str | Sequence[str] | None = "xdat29fav210"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SEED_STEAM = sa.text(
    """
    INSERT INTO container_profile (
        guid, name, kind, docker_image, runtime_profile, env,
        is_builtin, created_at, updated_at
    )
    SELECT
        gen_random_uuid(), 'steam', 'steam',
        'ghcr.io/games-on-whales/steam:edge', 'gow-app',
        CAST('{}' AS JSONB), true, NOW(), NOW()
    WHERE NOT EXISTS (
        SELECT 1 FROM container_profile WHERE name = 'steam'
    )
    """
)


def upgrade() -> None:
    op.create_table(
        "container_profile",
        sa.Column(
            "guid",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=True,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("docker_image", sa.String(), nullable=False),
        sa.Column(
            "runtime_profile",
            sa.String(),
            nullable=False,
            server_default="gow-app",
        ),
        sa.Column(
            "env",
            sa.JSON().with_variant(
                sa.dialects.postgresql.JSONB(), "postgresql"
            ),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "is_builtin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.UniqueConstraint("name", name="uq_container_profile_name"),
    )
    op.create_index(
        "ix_container_profile_name", "container_profile", ["name"]
    )
    op.create_index(
        "ix_container_profile_kind", "container_profile", ["kind"]
    )
    op.create_index(
        "ix_container_profile_is_builtin", "container_profile", ["is_builtin"]
    )

    # Idempotent seed of the builtin steam profile (preserves existing behaviour).
    op.execute(_SEED_STEAM)


def downgrade() -> None:
    op.drop_index(
        "ix_container_profile_is_builtin", table_name="container_profile"
    )
    op.drop_index("ix_container_profile_kind", table_name="container_profile")
    op.drop_index("ix_container_profile_name", table_name="container_profile")
    op.drop_table("container_profile")
