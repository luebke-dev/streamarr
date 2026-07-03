"""Schematize media_item.extra_data (TEXT -> JSONB) and retire favorite table

Revision ID: xdat29fav210
Revises: idxrfr001
Create Date: 2026-07-03 00:00:00.000000

Two data-architecture cleanups:

2.9 -- ``media_item.extra_data`` was ``TEXT`` holding a JSON *string* that was
       written inconsistently (the TMDB sync import wrote a bare language code
       like ``en`` -- not even JSON). Convert the column to ``JSONB`` so it can
       be queried structurally (the studio filter now uses ``->>'studio'``) and
       GIN-indexed. Existing values are migrated tolerantly: valid JSON is cast
       as-is; a bare language-code-looking string is wrapped as
       ``{"original_language": <val>}``; anything else becomes ``{"raw": <val>}``;
       NULL stays NULL. Invalid casts are caught per-row so one bad value cannot
       abort the whole ALTER.

2.10 -- the ``favorite`` table is dead (favorites live in ``list_item`` now).
       Drop it; downgrade recreates it empty.
"""

import sqlalchemy as sa

from alembic import op

revision = "xdat29fav210"
down_revision = "idxrfr001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- 2.9: extra_data TEXT -> JSONB -------------------------------------
    # Per-row tolerant converter: a plain ``val::jsonb`` would abort the whole
    # ALTER on the first non-JSON value (e.g. the bare ``en`` written by the
    # TMDB import), so wrap the cast in an exception handler.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION _extra_data_text_to_jsonb(val text)
        RETURNS jsonb AS $$
        BEGIN
            IF val IS NULL THEN
                RETURN NULL;
            END IF;
            BEGIN
                -- Valid JSON (object, array, quoted string, number, ...).
                RETURN val::jsonb;
            EXCEPTION WHEN others THEN
                -- Not valid JSON: bare string. Language-code shaped values
                -- (e.g. 'en', 'de', 'pt-BR') were written by the TMDB import.
                IF val ~ '^[A-Za-z]{2,3}([-_][A-Za-z0-9]+)?$' THEN
                    RETURN jsonb_build_object('original_language', val);
                ELSE
                    RETURN jsonb_build_object('raw', val);
                END IF;
            END;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        "ALTER TABLE media_item "
        "ALTER COLUMN extra_data TYPE jsonb "
        "USING _extra_data_text_to_jsonb(extra_data)"
    )
    op.execute("DROP FUNCTION _extra_data_text_to_jsonb(text)")

    # GIN index so structured lookups (studio filter, key containment) are fast.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_media_item_extra_data_gin "
        "ON media_item USING gin (extra_data)"
    )

    # --- 2.10: retire the orphaned favorite table --------------------------
    op.execute("DROP TABLE IF EXISTS favorite")


def downgrade() -> None:
    # --- 2.10: recreate favorite table (empty) -----------------------------
    op.create_table(
        "favorite",
        sa.Column(
            "guid",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("media_item_guid", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["media_item_guid"], ["media_item.guid"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user.guid"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("guid"),
        sa.UniqueConstraint(
            "user_id", "media_item_guid", name="uq_favorite_user_media"
        ),
    )
    op.create_index(
        op.f("ix_favorite_media_item_guid"),
        "favorite",
        ["media_item_guid"],
        unique=False,
    )
    op.create_index(
        op.f("ix_favorite_user_id"), "favorite", ["user_id"], unique=False
    )

    # --- 2.9: extra_data JSONB -> TEXT -------------------------------------
    op.execute("DROP INDEX IF EXISTS ix_media_item_extra_data_gin")
    op.execute(
        "ALTER TABLE media_item "
        "ALTER COLUMN extra_data TYPE text "
        "USING extra_data::text"
    )
