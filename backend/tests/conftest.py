"""Pytest configuration and fixtures for backend tests."""

import asyncio
import os
import uuid
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# Force-exit after pytest completes.
#
# Background: importing pyrate.worker creates a taskiq RedisStreamBroker that
# opens persistent Redis connections with non-daemon threads.  These threads
# prevent the Python interpreter from exiting after pytest finishes.  We
# capture the exit code and call os._exit() in pytest_unconfigure which runs
# after all plugins (including coverage) have finished their work.
# ---------------------------------------------------------------------------
_pytest_exit_code = 0


def pytest_sessionfinish(session, exitstatus):
    global _pytest_exit_code
    _pytest_exit_code = exitstatus


def pytest_unconfigure(config):
    import sys
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(_pytest_exit_code)


# Set test environment variables BEFORE any pyrate imports
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
_redis_url = os.environ.get("PYTEST_REDIS_URL") or os.environ.get(
    "REDIS_URL",
    "redis://localhost:6379/15",
)
if _redis_url.rsplit("/", 1)[-1] == "0":
    _redis_url = f"{_redis_url.rsplit('/', 1)[0]}/15"
os.environ["REDIS_URL"] = _redis_url


@pytest_asyncio.fixture(autouse=True)
async def _clear_test_redis():
    import redis.asyncio as redis

    client = redis.from_url(os.environ["REDIS_URL"])
    try:
        await client.flushdb()
    except Exception:
        pass
    finally:
        await client.aclose()


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """Reset the process-global settings cache between tests.

    ``pyrate.services.settings`` keeps a ``_cache: dict[str, Any]`` at
    module scope so production hot-path reads don't hit Postgres on every
    call. In tests this is observable as values bleeding across cases
    (e.g. ``tmdb_api_key`` from one test still resolving in the next).
    Each test starts with an empty cache; production behaviour is
    unaffected because every running process has its own dict.
    """
    from pyrate.services import settings as _settings_module

    _settings_module._cache.clear()
    yield
    _settings_module._cache.clear()

# Prevent the worker module from creating a real Redis broker connection
# that would keep the process alive after tests complete.
# We must force-replace the module since taskiq_redis may already be
# installed and importable.
import sys
from unittest.mock import MagicMock


class _FakeBroker:
    """A no-op broker that acts as a passthrough decorator."""

    def with_result_backend(self, *a, **kw):
        return self

    def with_middlewares(self, *a, **kw):
        return self

    def task(self, fn=None, **kw):
        if fn is not None:
            # @broker.task  (no parentheses)
            fn.kiq = MagicMock()
            return fn

        def wrapper(f):
            f.kiq = MagicMock()
            return f

        return wrapper

    def on_event(self, *events):
        # @broker.on_event(...) — passthrough decorator for startup hooks.
        def wrapper(f):
            return f

        return wrapper


_taskiq_redis_mod = MagicMock()
_taskiq_redis_mod.RedisStreamBroker.return_value = _FakeBroker()
_taskiq_redis_mod.RedisAsyncResultBackend.return_value = MagicMock()
sys.modules["taskiq_redis"] = _taskiq_redis_mod

# Now we can import pyrate modules safely
from sqlalchemy import event  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402

from pyrate.database import Base  # noqa: E402

# Import all models to ensure they are registered with SQLModel/SQLAlchemy
# This must be done before creating tables
from pyrate.models import (  # noqa: E402, F401
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
from pyrate.models.downloads import Download  # noqa: E402, F401
from pyrate.models.genre import Genre  # noqa: E402, F401
from pyrate.models.group import Group, UserGroupLink  # noqa: E402, F401
from pyrate.models.indexer import Indexer, IndexerCategory  # noqa: E402, F401
from pyrate.models.subscription import (  # noqa: E402, F401
    PaymentHistory,
    SubscriptionPackage,
    UserSession,
    UserSubscription,
)
from pyrate.models.viewing_history import ViewingHistory  # noqa: E402, F401
from pyrate.models.party import WatchParty, WatchPartyMember  # noqa: E402, F401
from pyrate.models.friendship import Friendship  # noqa: E402, F401
from pyrate.models.media import MediaFile, MediaItem  # noqa: E402, F401
from pyrate.models.library import Library  # noqa: E402, F401
from pyrate.models.page_layout import PageLayout, PageSection, SectionType  # noqa: E402, F401


# Configure pytest-asyncio
@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    # Cancel any lingering tasks so the loop can shut down cleanly.
    # Without this, background tasks (e.g. Redis subscriber loops) can
    # prevent the process from exiting after all tests have finished.
    pending = asyncio.all_tasks(loop)
    for task in pending:
        task.cancel()
    if pending:
        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
    loop.close()


# Database fixtures
@pytest_asyncio.fixture(scope="function")
async def test_db_engine():
    """Create a test database engine using an in-memory SQLite database."""
    # Use SQLite in-memory for fast tests
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )

    # Register PostgreSQL-specific functions for SQLite compatibility
    @event.listens_for(engine.sync_engine, "connect")
    def _register_functions(dbapi_conn, connection_record):
        dbapi_conn.create_function(
            "gen_random_uuid", 0, lambda: str(uuid.uuid4())
        )

    # Auto-generate UUID guids Python-side for SQLite (since server_default
    # gen_random_uuid() doesn't return the value back to SQLAlchemy for refresh)
    @event.listens_for(Session, "before_flush")
    def _set_uuid_defaults(session, flush_context, instances):
        for obj in session.new:
            if hasattr(obj, "guid") and obj.guid is None:
                obj.guid = uuid.uuid4()

    # Create all tables (both DeclarativeBase and SQLModel)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(SQLModel.metadata.create_all)

    yield engine

    # Clean up
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(test_db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create a database session for testing."""
    async_session_maker = async_sessionmaker(
        test_db_engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session_maker() as session:
        yield session
        await session.rollback()


# User fixtures
@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession) -> User:
    """Create a test user."""
    user = User(
        guid=uuid.uuid4(),
        email="test@example.com",
        first_name="Test",
        last_name="User",
        is_active=True,
        is_superuser=False,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_superuser(db_session: AsyncSession) -> User:
    """Create a test superuser."""
    user = User(
        guid=uuid.uuid4(),
        email="admin@example.com",
        first_name="Admin",
        last_name="User",
        is_active=True,
        is_superuser=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def test_user2(db_session: AsyncSession) -> User:
    """Create a second test user."""
    user = User(
        guid=uuid.uuid4(),
        email="test2@example.com",
        first_name="Test2",
        last_name="User2",
        is_active=True,
        is_superuser=False,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user
