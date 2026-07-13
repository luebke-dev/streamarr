"""Tests for PlayTokenService (Redis-backed play token management).

Uses fakeredis so no real Redis instance is required.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import fakeredis
import pytest
import pytest_asyncio

from streamarr.schemas.play_token import PlayToken, PlayTokenCreate
from streamarr.services.play_token import PlayTokenService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def redis_service() -> PlayTokenService:
    """Return a PlayTokenService wired to an in-memory FakeAsyncRedis."""
    service = PlayTokenService()
    service._redis = fakeredis.FakeAsyncRedis(decode_responses=True)
    return service


def _create_data(
    content_type: str = "movie",
    user_guid: uuid.UUID | None = None,
    content_id: uuid.UUID | None = None,
) -> PlayTokenCreate:
    return PlayTokenCreate(
        user_guid=user_guid or uuid.uuid4(),
        content_type=content_type,
        content_id=content_id or uuid.uuid4(),
        file_path="/library/movies/test.mkv",
    )


# ---------------------------------------------------------------------------
# create_token
# ---------------------------------------------------------------------------


class TestCreateToken:
    """Tests for PlayTokenService.create_token()."""

    @pytest.mark.asyncio
    async def test_create_token_returns_play_token(self, redis_service: PlayTokenService):
        """create_token returns a PlayToken with the correct fields."""
        data = _create_data()
        token = await redis_service.create_token(data)

        assert isinstance(token, PlayToken)
        assert token.content_type == "movie"
        assert token.user_guid == str(data.user_guid)
        assert token.content_id == str(data.content_id)
        assert token.file_path == "/library/movies/test.mkv"
        assert token.token  # non-empty string

    @pytest.mark.asyncio
    async def test_create_token_is_persisted(self, redis_service: PlayTokenService):
        """Token created by create_token is immediately retrievable."""
        data = _create_data()
        created = await redis_service.create_token(data)

        retrieved = await redis_service.get_token(created.token)
        assert retrieved is not None
        assert retrieved.token == created.token

    @pytest.mark.asyncio
    async def test_two_tokens_are_unique(self, redis_service: PlayTokenService):
        """Each call generates a unique token string."""
        data = _create_data()
        t1 = await redis_service.create_token(data)
        t2 = await redis_service.create_token(data)

        assert t1.token != t2.token

    @pytest.mark.asyncio
    async def test_create_token_episode_type(self, redis_service: PlayTokenService):
        """Token can be created for episode content type."""
        data = _create_data(content_type="episode")
        token = await redis_service.create_token(data)

        assert token.content_type == "episode"

    @pytest.mark.asyncio
    async def test_create_token_timestamps_set(self, redis_service: PlayTokenService):
        """created_at and last_accessed_at are set to approximately now."""
        before = datetime.now(UTC) - timedelta(seconds=1)
        data = _create_data()
        token = await redis_service.create_token(data)
        after = datetime.now(UTC) + timedelta(seconds=1)

        assert before <= token.created_at <= after
        assert before <= token.last_accessed_at <= after


# ---------------------------------------------------------------------------
# get_token
# ---------------------------------------------------------------------------


class TestGetToken:
    """Tests for PlayTokenService.get_token()."""

    @pytest.mark.asyncio
    async def test_get_token_not_found_returns_none(self, redis_service: PlayTokenService):
        """get_token returns None for a nonexistent token string."""
        result = await redis_service.get_token("no_such_token")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_token_preserves_all_fields(self, redis_service: PlayTokenService):
        """Stored and retrieved tokens have identical fields."""
        user_id = uuid.uuid4()
        content_id = uuid.uuid4()
        data = _create_data(user_guid=user_id, content_id=content_id)
        created = await redis_service.create_token(data)

        retrieved = await redis_service.get_token(created.token)

        assert retrieved.token == created.token
        assert retrieved.user_guid == str(user_id)
        assert retrieved.content_id == str(content_id)
        assert retrieved.content_type == "movie"
        assert retrieved.file_path == "/library/movies/test.mkv"
        assert retrieved.session_id is None


# ---------------------------------------------------------------------------
# extend_ttl
# ---------------------------------------------------------------------------


class TestExtendTtl:
    """Tests for PlayTokenService.extend_ttl()."""

    @pytest.mark.asyncio
    async def test_extend_ttl_returns_true(self, redis_service: PlayTokenService):
        """extend_ttl returns True for an existing token."""
        data = _create_data()
        created = await redis_service.create_token(data)

        result = await redis_service.extend_ttl(created.token)
        assert result is True

    @pytest.mark.asyncio
    async def test_extend_ttl_updates_last_accessed(self, redis_service: PlayTokenService):
        """extend_ttl updates last_accessed_at to approximately now."""
        data = _create_data()
        created = await redis_service.create_token(data)

        before = datetime.now(UTC) - timedelta(seconds=1)
        await redis_service.extend_ttl(created.token)
        after = datetime.now(UTC) + timedelta(seconds=1)

        updated = await redis_service.get_token(created.token)
        assert before <= updated.last_accessed_at <= after

    @pytest.mark.asyncio
    async def test_extend_ttl_nonexistent_returns_false(self, redis_service: PlayTokenService):
        """extend_ttl returns False when the token does not exist."""
        result = await redis_service.extend_ttl("ghost_token")
        assert result is False

    @pytest.mark.asyncio
    async def test_extend_ttl_preserves_other_fields(self, redis_service: PlayTokenService):
        """extend_ttl does not overwrite content fields."""
        data = _create_data(content_type="episode")
        created = await redis_service.create_token(data)
        await redis_service.extend_ttl(created.token)

        refreshed = await redis_service.get_token(created.token)
        assert refreshed.content_type == "episode"
        assert refreshed.content_id == created.content_id


# ---------------------------------------------------------------------------
# update_session_id
# ---------------------------------------------------------------------------


class TestUpdateSessionId:
    """Tests for PlayTokenService.update_session_id()."""

    @pytest.mark.asyncio
    async def test_update_session_id_sets_value(self, redis_service: PlayTokenService):
        """update_session_id stores the session_id on the token."""
        data = _create_data()
        created = await redis_service.create_token(data)

        result = await redis_service.update_session_id(created.token, "sess-abc-123")
        assert result is True

        updated = await redis_service.get_token(created.token)
        assert updated.session_id == "sess-abc-123"

    @pytest.mark.asyncio
    async def test_update_session_id_nonexistent_returns_false(
        self, redis_service: PlayTokenService
    ):
        """update_session_id returns False for a missing token."""
        result = await redis_service.update_session_id("ghost", "sess-xyz")
        assert result is False

    @pytest.mark.asyncio
    async def test_update_session_id_updates_last_accessed(
        self, redis_service: PlayTokenService
    ):
        """update_session_id also refreshes last_accessed_at."""
        data = _create_data()
        created = await redis_service.create_token(data)

        before = datetime.now(UTC) - timedelta(seconds=1)
        await redis_service.update_session_id(created.token, "sess-001")
        after = datetime.now(UTC) + timedelta(seconds=1)

        updated = await redis_service.get_token(created.token)
        assert before <= updated.last_accessed_at <= after


# ---------------------------------------------------------------------------
# delete_token
# ---------------------------------------------------------------------------


class TestDeleteToken:
    """Tests for PlayTokenService.delete_token()."""

    @pytest.mark.asyncio
    async def test_delete_token_removes_it(self, redis_service: PlayTokenService):
        """Deleted tokens are no longer retrievable."""
        data = _create_data()
        created = await redis_service.create_token(data)

        await redis_service.delete_token(created.token)

        assert await redis_service.get_token(created.token) is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_true(self, redis_service: PlayTokenService):
        """Deleting a nonexistent token still returns True (idempotent)."""
        result = await redis_service.delete_token("nonexistent_token_xyz")
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_removes_from_all_tokens(self, redis_service: PlayTokenService):
        """Deleted token no longer appears in get_all_tokens()."""
        data = _create_data()
        created = await redis_service.create_token(data)

        await redis_service.delete_token(created.token)

        all_tokens = await redis_service.get_all_tokens()
        assert not any(t.token == created.token for t in all_tokens)


# ---------------------------------------------------------------------------
# get_all_tokens
# ---------------------------------------------------------------------------


class TestGetAllTokens:
    """Tests for PlayTokenService.get_all_tokens()."""

    @pytest.mark.asyncio
    async def test_get_all_tokens_empty(self, redis_service: PlayTokenService):
        """get_all_tokens returns empty list when no tokens exist."""
        tokens = await redis_service.get_all_tokens()
        assert tokens == []

    @pytest.mark.asyncio
    async def test_get_all_tokens_multiple(self, redis_service: PlayTokenService):
        """get_all_tokens returns all created tokens."""
        t1 = await redis_service.create_token(_create_data())
        t2 = await redis_service.create_token(_create_data())
        t3 = await redis_service.create_token(_create_data())

        all_tokens = await redis_service.get_all_tokens()
        token_strings = {t.token for t in all_tokens}

        assert t1.token in token_strings
        assert t2.token in token_strings
        assert t3.token in token_strings

    @pytest.mark.asyncio
    async def test_get_all_tokens_count_after_delete(self, redis_service: PlayTokenService):
        """get_all_tokens reflects deletions correctly."""
        t1 = await redis_service.create_token(_create_data())
        t2 = await redis_service.create_token(_create_data())

        await redis_service.delete_token(t1.token)

        all_tokens = await redis_service.get_all_tokens()
        assert len(all_tokens) == 1
        assert all_tokens[0].token == t2.token


# ---------------------------------------------------------------------------
# get_user_tokens
# ---------------------------------------------------------------------------


class TestGetUserTokens:
    """Tests for PlayTokenService.get_user_tokens()."""

    @pytest.mark.asyncio
    async def test_get_user_tokens_filters_by_user(self, redis_service: PlayTokenService):
        """get_user_tokens returns only tokens belonging to the requested user."""
        user_a = uuid.uuid4()
        user_b = uuid.uuid4()

        await redis_service.create_token(_create_data(user_guid=user_a))
        await redis_service.create_token(_create_data(user_guid=user_a))
        await redis_service.create_token(_create_data(user_guid=user_b))

        tokens_a = await redis_service.get_user_tokens(str(user_a))
        assert len(tokens_a) == 2
        assert all(t.user_guid == str(user_a) for t in tokens_a)

    @pytest.mark.asyncio
    async def test_get_user_tokens_empty_for_unknown_user(
        self, redis_service: PlayTokenService
    ):
        """get_user_tokens returns empty list for a user with no tokens."""
        await redis_service.create_token(_create_data())  # someone else's token

        tokens = await redis_service.get_user_tokens(str(uuid.uuid4()))
        assert tokens == []
