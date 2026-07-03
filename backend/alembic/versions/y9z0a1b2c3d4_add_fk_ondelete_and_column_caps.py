"""Add ONDELETE actions to user/subscription FKs and cap a few string columns.

Revision ID: y9z0a1b2c3d4
Revises: x8y9z0a1b2c3
Create Date: 2026-04-18 12:00:00.000000

What this does:

* Replaces unqualified ``REFERENCES user(guid)`` foreign keys with explicit
  ``ON DELETE`` behaviour. Until now, deleting a user would either fail
  (Postgres default NO ACTION) or leave dangling rows in the application's
  weakly-linked tables. Each side gets the behaviour that matches what the
  application actually wants:

    - ``CASCADE`` — the dependent row is meaningless without the user:
      devices, viewing history, notifications, sessions, user-subscriptions,
      created invites, user↔group links.
    - ``SET NULL`` — the record should survive but decouple: invite
      ``used_by_user_id`` (audit trail of who consumed an invite).
    - ``RESTRICT`` — financial records (payment_history) must be dealt with
      by an admin before the user/subscription can be removed.

* Adds length caps to notification.subject (varchar(500)), currency
  (varchar(10)) and payment_history.status (varchar(32)). These were
  unbounded ``text`` columns before.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "y9z0a1b2c3d4"
down_revision: Union[str, Sequence[str], None] = "x8y9z0a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, column, fk_constraint_name, referenced_table, referenced_column, new_ondelete)
_FKS_TO_UPDATE: list[tuple[str, str, str, str, str, str]] = [
    # CASCADE group — dependent rows are meaningless without the user
    ("device", "user_id", "device_user_id_fkey", "user", "guid", "CASCADE"),
    ("viewing_history", "user_guid", "viewing_history_user_guid_fkey", "user", "guid", "CASCADE"),
    ("notification", "user_id", "notification_user_id_fkey", "user", "guid", "CASCADE"),
    ("user_subscription", "user_id", "user_subscription_user_id_fkey", "user", "guid", "CASCADE"),
    ("user_session", "user_id", "user_session_user_id_fkey", "user", "guid", "CASCADE"),
    ("user_session", "subscription_id", "user_session_subscription_id_fkey", "user_subscription", "guid", "CASCADE"),
    ("user_group_link", "user_id", "user_group_link_user_id_fkey", "user", "guid", "CASCADE"),
    ("user_group_link", "group_id", "user_group_link_group_id_fkey", "group", "guid", "CASCADE"),
    ("invite", "created_by_user_id", "invite_created_by_user_id_fkey", "user", "guid", "CASCADE"),

    # SET NULL — audit records that should outlive the user
    ("invite", "used_by_user_id", "invite_used_by_user_id_fkey", "user", "guid", "SET NULL"),

    # RESTRICT — financial records require explicit admin cleanup
    ("user_subscription", "package_id", "user_subscription_package_id_fkey", "subscription_package", "guid", "RESTRICT"),
    ("payment_history", "user_id", "payment_history_user_id_fkey", "user", "guid", "RESTRICT"),
    ("payment_history", "subscription_id", "payment_history_subscription_id_fkey", "user_subscription", "guid", "RESTRICT"),
]


def upgrade() -> None:
    for table, column, fk_name, ref_table, ref_col, ondelete in _FKS_TO_UPDATE:
        op.execute(f'ALTER TABLE "{table}" DROP CONSTRAINT IF EXISTS {fk_name}')
        op.create_foreign_key(
            fk_name,
            table,
            ref_table,
            [column],
            [ref_col],
            ondelete=ondelete,
        )

    # Column caps. These are lossless casts because no existing row comes
    # close to the new caps (subjects ~titles, status is a handful of values).
    op.execute(
        "ALTER TABLE notification ALTER COLUMN subject TYPE VARCHAR(500) USING substr(subject, 1, 500)"
    )
    op.execute(
        "ALTER TABLE payment_history ALTER COLUMN currency TYPE VARCHAR(10) USING substr(currency, 1, 10)"
    )
    op.execute(
        "ALTER TABLE payment_history ALTER COLUMN status TYPE VARCHAR(32) USING substr(status, 1, 32)"
    )


def downgrade() -> None:
    # Re-widen the capped columns first.
    op.execute("ALTER TABLE payment_history ALTER COLUMN status TYPE TEXT")
    op.execute("ALTER TABLE payment_history ALTER COLUMN currency TYPE TEXT")
    op.execute("ALTER TABLE notification ALTER COLUMN subject TYPE TEXT")

    for table, column, fk_name, ref_table, ref_col, _ondelete in _FKS_TO_UPDATE:
        op.execute(f'ALTER TABLE "{table}" DROP CONSTRAINT IF EXISTS {fk_name}')
        op.create_foreign_key(
            fk_name,
            table,
            ref_table,
            [column],
            [ref_col],
        )
