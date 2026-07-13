import contextlib
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from streamarr.config import settings


class Base(DeclarativeBase):
    # https://docs.sqlalchemy.org/en/14/orm/extensions/asyncio.html#preventing-implicit-io-when-using-asyncsession
    __mapper_args__ = {"eager_defaults": True}
    # Map Python datetime to TIMESTAMP WITH TIME ZONE globally
    type_annotation_map = {
        datetime: DateTime(timezone=True),
    }


# Heavily inspired by https://praciano.com.br/fastapi-and-async-sqlalchemy-20-with-pytest-done-right.html
class DatabaseSessionManager:
    def __init__(self, host: str, engine_kwargs: dict[str, Any] | None = None):
        if engine_kwargs is None:
            engine_kwargs = {}
        # Configure connection pool settings
        # Keep pool small since multiple services share the database
        # PostgreSQL default max_connections is 100
        # With 3 workers + backend + scheduler = 5 services
        # PostgreSQL max_connections=200, so ~35-40 per service is safe
        # SQLite doesn't support these pool settings, so only add them for PostgreSQL
        default_engine_kwargs = {}

        if "sqlite" not in host.lower():
            default_engine_kwargs = {
                "pool_size": 10,  # Base pool size per service
                "max_overflow": 25,  # Allow overflow for burst tasks
                "pool_timeout": 30,  # Timeout for getting connection from pool
                "pool_recycle": 1800,  # Recycle connections every 30 minutes
                "pool_pre_ping": True,  # Validate connections before use
            }

        default_engine_kwargs.update(engine_kwargs)

        self._engine = create_async_engine(host, **default_engine_kwargs)
        self._sessionmaker = async_sessionmaker(
            autocommit=False, bind=self._engine, expire_on_commit=False
        )

    async def close(self):
        if self._engine is None:
            raise Exception("DatabaseSessionManager is not initialized")
        await self._engine.dispose()

        self._engine = None
        self._sessionmaker = None

    @contextlib.asynccontextmanager
    async def connect(self) -> AsyncIterator[AsyncConnection]:
        if self._engine is None:
            raise Exception("DatabaseSessionManager is not initialized")

        async with self._engine.begin() as connection:
            try:
                yield connection
            except Exception:
                await connection.rollback()
                raise

    @contextlib.asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        if self._sessionmaker is None:
            raise Exception("DatabaseSessionManager is not initialized")

        session = self._sessionmaker()
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


sessionmanager = DatabaseSessionManager(settings.database_url, {"echo": False})


async def get_db_session():
    async with sessionmanager.session() as session:
        yield session
