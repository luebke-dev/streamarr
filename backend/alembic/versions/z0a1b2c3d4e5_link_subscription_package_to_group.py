"""link subscription_package to group (1:1) and drop per-package permission columns

Revision ID: z0a1b2c3d4e5
Revises: y9z0a1b2c3d4
Create Date: 2026-04-19 00:00:00.000000

This migration unifies subscription permissions with the Group permission system:

- Adds ``subscription_package.group_id`` (FK -> group.guid, ondelete RESTRICT, NOT NULL)
- For each existing package, auto-creates a Group named "Subscription: <name>" and
  copies the package's permission fields into the group:
    * package.allowed_libraries          -> group.allowed_libraries
    * max_quality_movies / _series       -> group.max_video_quality (max of both)
    * max_quality_music                  -> group.max_audio_quality
    * max_concurrent_sessions            -> group.max_concurrent_streams
- Drops per-package permission columns (single source of truth = Group).
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "z0a1b2c3d4e5"
down_revision: str | None = "y9z0a1b2c3d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Quality ranking for merging movies+series quality into a single video quality
_VIDEO_RANK = {"sd": 1, "hd": 2, "fhd": 3, "uhd": 4}
_AUDIO_RANK = {"lossy": 1, "lossless": 2}


def _max_video(a: str | None, b: str | None) -> str:
    ra = _VIDEO_RANK.get((a or "").lower(), 0)
    rb = _VIDEO_RANK.get((b or "").lower(), 0)
    winner = a if ra >= rb else b
    return (winner or "uhd").lower()


def _max_audio(a: str | None) -> str:
    return (a or "lossless").lower() if (a or "").lower() in _AUDIO_RANK else "lossless"


def upgrade() -> None:
    bind = op.get_bind()

    # 1) Add nullable group_id (will be backfilled, then made NOT NULL)
    op.add_column(
        "subscription_package",
        sa.Column("group_id", sa.Uuid(), nullable=True),
    )

    # 2) Data migration: for each package create a dedicated group + link
    packages = bind.execute(
        sa.text(
            "SELECT guid, name, allowed_libraries, max_quality_movies, "
            "max_quality_series, max_quality_music, max_concurrent_sessions "
            "FROM subscription_package"
        )
    ).fetchall()

    for pkg in packages:
        pkg_guid = pkg[0]
        pkg_name = pkg[1]
        allowed_libs = pkg[2] or []
        q_movies = pkg[3]
        q_series = pkg[4]
        q_music = pkg[5]
        sessions = pkg[6] or 1

        video_q = _max_video(q_movies, q_series)
        audio_q = _max_audio(q_music)

        group_name = f"Subscription: {pkg_name}"

        # Create the group; if a group with that name already exists (idempotent
        # re-run after a partial failure), just reuse it.
        existing = bind.execute(
            sa.text("SELECT guid FROM \"group\" WHERE name = :n"),
            {"n": group_name},
        ).fetchone()

        if existing:
            group_guid = existing[0]
        else:
            new_group = bind.execute(
                sa.text(
                    "INSERT INTO \"group\" "
                    "(name, description, is_active, allowed_libraries, "
                    " max_concurrent_streams, max_game_streams, "
                    " offline_download_period_minutes, prefetch_period_minutes, "
                    " on_demand_fetch_period_minutes, max_video_quality, "
                    " max_audio_quality, indexer_api_requests_period_minutes, "
                    " indexer_downloads_period_minutes, playback_period_minutes, "
                    " max_concurrent_transcodings, favorites_permanent) "
                    "VALUES (:name, :desc, true, CAST(:libs AS json), "
                    " :streams, 0, 1440, 1440, 1440, :vq, :aq, "
                    " 60, 1440, 1440, 1, false) "
                    "RETURNING guid"
                ),
                {
                    "name": group_name,
                    "desc": f"Auto-created group for subscription package {pkg_name}",
                    "libs": json.dumps(allowed_libs),
                    "streams": int(sessions),
                    "vq": video_q,
                    "aq": audio_q,
                },
            ).fetchone()
            group_guid = new_group[0]

        bind.execute(
            sa.text(
                "UPDATE subscription_package SET group_id = :gid WHERE guid = :pid"
            ),
            {"gid": group_guid, "pid": pkg_guid},
        )

    # 3) Enforce NOT NULL + FK + index
    op.alter_column("subscription_package", "group_id", nullable=False)
    op.create_foreign_key(
        "fk_subscription_package_group_id",
        "subscription_package",
        "group",
        ["group_id"],
        ["guid"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_subscription_package_group_id",
        "subscription_package",
        ["group_id"],
    )

    # 4) Drop legacy permission columns (Group is now the source of truth)
    op.drop_column("subscription_package", "allowed_libraries")
    op.drop_column("subscription_package", "max_quality_movies")
    op.drop_column("subscription_package", "max_quality_series")
    op.drop_column("subscription_package", "max_quality_music")
    op.drop_column("subscription_package", "max_concurrent_sessions")


def _json_literal(value) -> str:
    """(Deprecated, kept for downgrade safety.) Return a JSON literal."""
    return json.dumps(value)


def downgrade() -> None:
    # Re-create the legacy columns (best-effort: data is restored from group)
    op.add_column(
        "subscription_package",
        sa.Column(
            "allowed_libraries",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )
    op.add_column(
        "subscription_package",
        sa.Column(
            "max_quality_movies",
            sa.String(),
            nullable=False,
            server_default=sa.text("'uhd'"),
        ),
    )
    op.add_column(
        "subscription_package",
        sa.Column(
            "max_quality_series",
            sa.String(),
            nullable=False,
            server_default=sa.text("'uhd'"),
        ),
    )
    op.add_column(
        "subscription_package",
        sa.Column(
            "max_quality_music",
            sa.String(),
            nullable=False,
            server_default=sa.text("'lossless'"),
        ),
    )
    op.add_column(
        "subscription_package",
        sa.Column(
            "max_concurrent_sessions",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )

    # Best-effort backfill from the linked group
    op.execute(
        """
        UPDATE subscription_package AS p
        SET allowed_libraries = g.allowed_libraries,
            max_quality_movies = COALESCE(g.max_video_quality, 'uhd'),
            max_quality_series = COALESCE(g.max_video_quality, 'uhd'),
            max_quality_music = COALESCE(g.max_audio_quality, 'lossless'),
            max_concurrent_sessions = g.max_concurrent_streams
        FROM "group" AS g
        WHERE p.group_id = g.guid
        """
    )

    op.drop_index("ix_subscription_package_group_id", table_name="subscription_package")
    op.drop_constraint(
        "fk_subscription_package_group_id",
        "subscription_package",
        type_="foreignkey",
    )
    op.drop_column("subscription_package", "group_id")
