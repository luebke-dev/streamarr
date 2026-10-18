#!/usr/bin/env python3
"""Issue (or reuse) a Streamarr API key for the desktop-app test suite.

Runs inside the backend container so it can use the application's own
``generate_api_key``/``hash_api_key`` helpers. Those are the single source of
truth for the key format; writing a key row by hand here would risk a format
that the authenticating dependency rejects.

Usage (on the server):
    docker exec app-backend-python-1 python3 - < issue_key.py <email> <name>

Prints the raw key to stdout on first creation. On a repeat run for an existing
key name it cannot recover the raw value (only the hash is stored), so it
revokes nothing and simply says so — rerun with a new name instead.
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select

from streamarr.auth.api_key_utils import (
    api_key_display_prefix,
    generate_api_key,
    hash_api_key,
)
from streamarr.database import get_db_session
from streamarr.models.api_key import ApiKey
from streamarr.models.user import User


async def issue(email: str, name: str) -> int:
    async for session in get_db_session():
        user = (
            await session.execute(select(User).where(User.email == email))
        ).scalars().first()
        if user is None:
            print(f"ERROR: no user with email {email!r}", file=sys.stderr)
            return 2

        existing = (
            await session.execute(
                select(ApiKey).where(
                    ApiKey.name == name,
                    ApiKey.user_guid == user.guid,
                    ApiKey.revoked_at.is_(None),
                )
            )
        ).scalars().first()
        if existing is not None:
            print(
                f"EXISTS prefix={existing.key_prefix} created={existing.created_at} "
                f"last_used={existing.last_used_at}",
                file=sys.stderr,
            )
            print("NOTE: the raw key is not recoverable; use a new --name to reissue.")
            return 0

        raw = generate_api_key()
        session.add(
            ApiKey(
                name=name,
                key_prefix=api_key_display_prefix(raw),
                key_hash=hash_api_key(raw),
                user_guid=user.guid,
                created_by_guid=user.guid,
            )
        )
        await session.commit()
        print(f"ISSUED user={email} name={name}", file=sys.stderr)
        # Raw key on stdout only, so callers can pipe it somewhere safe without
        # capturing diagnostics.
        print(raw)
        return 0

    print("ERROR: could not obtain a database session", file=sys.stderr)
    return 3


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: issue_key.py <email> <name>", file=sys.stderr)
        raise SystemExit(64)
    raise SystemExit(asyncio.run(issue(sys.argv[1], sys.argv[2])))
