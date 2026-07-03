"""Shared fixtures for API integration tests.

Provides a FastAPI TestClient with an in-memory SQLite database,
auth token helpers, and pre-created user fixtures.
"""

import asyncio
import os
import uuid as uuid_mod
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from pyrate.auth.jwt_handler import jwt_handler
from pyrate.database import Base

# Import all models to register them with SQLAlchemy/SQLModel metadata
from pyrate.models import (  # noqa: F401
    ActivityLog,
    ApiKey,
    Device,
    Downloader,
    Favorite,
    Invite,
    List,
    ListItem,
    Notification,
    NotificationStatus,
    NotificationType,
    Setting,
    User,
    UserListInteraction,
)
from pyrate.models.downloads import Download  # noqa: F401
from pyrate.models.genre import Genre  # noqa: F401
from pyrate.models.group import Group, UserGroupLink  # noqa: F401
from pyrate.models.indexer import Indexer, IndexerCategory  # noqa: F401
from pyrate.models.library import Library  # noqa: F401
from pyrate.models.media import MediaItem, MediaType  # noqa: F401
from pyrate.models.party import WatchParty, WatchPartyMember  # noqa: F401
from pyrate.models.person import MediaCast, Person  # noqa: F401
from pyrate.models.subscription import (  # noqa: F401
    PaymentHistory,
    SubscriptionPackage,
    UserSession,
    UserSubscription,
)
from pyrate.models.viewing_history import ViewingHistory  # noqa: F401


# ---------------------------------------------------------------------------
# Engine & session fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _ssrf_guard_resolves_test_hosts():
    """Test hosts (``*.example``, ``*.example.com`` subdomains) don't resolve via
    real DNS, which the SSRF guard would reject. Treat them as a public address
    so integration tests exercise endpoint logic; the guard's IP policy is
    covered by its own unit tests."""
    import ipaddress
    from unittest.mock import patch

    with patch(
        "pyrate.utils.net._resolve_host",
        return_value=[ipaddress.ip_address("93.184.216.34")],
    ):
        yield


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    # Cancel lingering tasks so the process exits cleanly in CI.
    pending = asyncio.all_tasks(loop)
    for task in pending:
        task.cancel()
    if pending:
        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def test_db_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _register_functions(dbapi_conn, _connection_record):
        dbapi_conn.create_function("gen_random_uuid", 0, lambda: str(uuid_mod.uuid4()))

    @event.listens_for(Session, "before_flush")
    def _set_uuid_defaults(session, _flush_context, _instances):
        for obj in session.new:
            if hasattr(obj, "guid") and obj.guid is None:
                obj.guid = uuid_mod.uuid4()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(SQLModel.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(test_db_engine) -> AsyncGenerator[AsyncSession]:
    maker = async_sessionmaker(
        test_db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with maker() as session:
        yield session
        await session.rollback()


# ---------------------------------------------------------------------------
# SQLite-compatible auth dependency overrides
#
# The production auth dependencies call ``session.get(User, user_id)`` where
# ``user_id`` is a **string** from the JWT ``sub`` claim.  PostgreSQL's Uuid
# column type happily coerces strings, but SQLite's Uuid type processor calls
# ``value.hex`` which fails on bare strings.
#
# The overrides below replicate the production logic but convert the string
# user_id to ``uuid.UUID`` before the lookup so SQLite works correctly.
# ---------------------------------------------------------------------------
_security = HTTPBearer(auto_error=False)


def _make_auth_overrides(db_dependency):
    """Create auth dependency overrides that share the request's DB session.

    By using ``Depends(db_dependency)`` (the same function that the endpoint's
    ``db`` parameter resolves to), FastAPI deduplicates the dependency and both
    the auth override and the endpoint receive the **same** session.  This is
    critical for endpoints that modify ``current_user`` via ``db.commit()``.
    """

    async def _get_user_from_token(token: str, session: AsyncSession) -> User | None:
        payload = jwt_handler.verify_token(token)
        if not payload or payload.get("type") != "access":
            return None
        user_id = payload.get("sub")
        if not user_id:
            return None
        try:
            uid = uuid_mod.UUID(user_id)
        except (ValueError, AttributeError):
            return None
        user = await session.get(User, uid)
        if not user or not user.is_active:
            return None
        return user

    async def override_get_current_user_optional(
        credentials: HTTPAuthorizationCredentials | None = Depends(_security),
        session: AsyncSession = Depends(db_dependency),
    ) -> User | None:
        if not credentials:
            return None
        return await _get_user_from_token(credentials.credentials, session)

    async def override_get_current_user(
        credentials: HTTPAuthorizationCredentials | None = Depends(_security),
        session: AsyncSession = Depends(db_dependency),
    ) -> User:
        if not credentials:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )
        user = await _get_user_from_token(credentials.credentials, session)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token or user not found",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return user

    async def override_get_current_superuser(
        credentials: HTTPAuthorizationCredentials | None = Depends(_security),
        session: AsyncSession = Depends(db_dependency),
    ) -> User:
        if not credentials:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )
        user = await _get_user_from_token(credentials.credentials, session)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token or user not found",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not user.is_superuser:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not enough permissions",
            )
        return user

    async def override_verify_refresh_token(
        credentials: HTTPAuthorizationCredentials | None = Depends(_security),
        session: AsyncSession = Depends(db_dependency),
    ) -> tuple[User, str]:
        if not credentials:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated",
                headers={"WWW-Authenticate": "Bearer"},
            )
        token = credentials.credentials
        payload = jwt_handler.verify_token(token)
        if not payload or payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        user_id = payload.get("sub")
        jti = payload.get("jti")
        if not user_id or not jti:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload",
                headers={"WWW-Authenticate": "Bearer"},
            )
        try:
            uid = uuid_mod.UUID(user_id)
        except (ValueError, AttributeError):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid user id in token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        user = await session.get(User, uid)
        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found or disabled",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return user, jti

    return (
        override_get_current_user_optional,
        override_get_current_user,
        override_get_current_superuser,
        override_verify_refresh_token,
    )


# ---------------------------------------------------------------------------
# FastAPI app with overridden DB + auth dependencies
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture(scope="function")
async def client(test_db_engine) -> AsyncGenerator[AsyncClient]:
    """Provide an httpx AsyncClient wired to the FastAPI app with test DB."""
    from pyrate.auth.dependencies import (
        get_current_superuser,
        get_current_user,
        get_current_user_optional,
        verify_refresh_token,
    )
    from pyrate.database import get_db_session
    from pyrate.web import app

    maker = async_sessionmaker(
        test_db_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def _override_db():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_db_session] = _override_db

    (
        override_optional,
        override_user,
        override_superuser,
        override_refresh,
    ) = _make_auth_overrides(get_db_session)
    app.dependency_overrides[get_current_user_optional] = override_optional
    app.dependency_overrides[get_current_user] = override_user
    app.dependency_overrides[get_current_superuser] = override_superuser
    app.dependency_overrides[verify_refresh_token] = override_refresh

    transport = ASGITransport(
        app=app,
        raise_app_exceptions=os.getenv("PYTEST_RAISE_APP_EXCEPTIONS") == "1",
    )
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# User helpers
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> User:
    user = User(
        guid=uuid_mod.uuid4(),
        email="apitest@example.com",
        first_name="API",
        last_name="Tester",
        is_active=True,
        is_superuser=False,
        email_verified=True,
        hashed_password=jwt_handler.get_password_hash("TestPassword123"),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_superuser(db_session: AsyncSession) -> User:
    user = User(
        guid=uuid_mod.uuid4(),
        email="apiadmin@example.com",
        first_name="API",
        last_name="Admin",
        is_active=True,
        is_superuser=True,
        email_verified=True,
        hashed_password=jwt_handler.get_password_hash("AdminPassword123"),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Auth header helpers
# ---------------------------------------------------------------------------
def auth_headers(user: User) -> dict[str, str]:
    """Return Bearer-auth headers for the given user."""
    token = jwt_handler.create_access_token({"sub": str(user.guid)})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def user_headers(test_user) -> dict[str, str]:
    return auth_headers(test_user)


@pytest.fixture
def admin_headers(test_superuser) -> dict[str, str]:
    return auth_headers(test_superuser)
