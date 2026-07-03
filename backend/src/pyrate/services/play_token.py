"""Play token service for managing playback tokens in Redis."""

import json
import logging
import secrets
from datetime import UTC, datetime

import redis.asyncio as redis

from pyrate.config import settings
from pyrate.schemas.play_token import PlayToken, PlayTokenCreate

logger = logging.getLogger(__name__)

# Redis key prefix for play tokens
REDIS_KEY_PREFIX = "pyrate:play:token:"
REDIS_TOKENS_SET = "pyrate:play:tokens"

# Default TTL for play tokens (2 hours in seconds)
DEFAULT_TOKEN_TTL = 2 * 60 * 60


def _mask_token(token: str) -> str:
    if not token:
        return "<none>"
    return f"{token[:6]}...<redacted>"


class PlayTokenService:
    """Service for managing play tokens in Redis."""

    def __init__(self):
        self._redis: redis.Redis | None = None

    async def _get_redis(self) -> redis.Redis:
        """Get or create Redis connection."""
        if self._redis is None:
            self._redis = redis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._redis

    async def close(self):
        """Close Redis connection."""
        if self._redis:
            await self._redis.aclose()
            self._redis = None

    def _get_token_key(self, token: str) -> str:
        """Get Redis key for a token."""
        return f"{REDIS_KEY_PREFIX}{token}"

    def _generate_token(self) -> str:
        """Generate a secure random token."""
        return secrets.token_urlsafe(32)

    async def create_token(
        self, token_data: PlayTokenCreate, ttl: int = DEFAULT_TOKEN_TTL
    ) -> PlayToken:
        """Create a new play token in Redis.

        Args:
            token_data: Token creation data
            ttl: Time to live in seconds (default 2 hours)

        Returns:
            The created PlayToken
        """
        r = await self._get_redis()

        token = PlayToken(
            token=self._generate_token(),
            user_guid=str(token_data.user_guid),
            content_type=token_data.content_type,
            content_id=str(token_data.content_id),
            file_path=token_data.file_path,
            created_at=datetime.now(UTC),
            last_accessed_at=datetime.now(UTC),
        )

        token_key = self._get_token_key(token.token)
        token_data_json = json.dumps(token.to_redis_dict())

        # Store token with TTL
        await r.set(token_key, token_data_json, ex=ttl)

        # Add to tokens set
        await r.sadd(REDIS_TOKENS_SET, token.token)

        logger.info(
            "Created play token: %s for %s %s (user: %s)",
            _mask_token(token.token), token.content_type, token.content_id,
            token.user_guid,
        )

        return token

    async def get_token(self, token: str) -> PlayToken | None:
        """Get a play token by token string.

        Args:
            token: The token string

        Returns:
            The PlayToken if found, None otherwise
        """
        r = await self._get_redis()

        token_key = self._get_token_key(token)
        token_data = await r.get(token_key)

        if not token_data:
            return None

        try:
            data = json.loads(token_data)
            return PlayToken.from_redis_dict(data)
        except (json.JSONDecodeError, KeyError) as e:
            logger.error("Error parsing token data for %s: %s", _mask_token(token), e)
            return None

    async def extend_ttl(self, token: str, ttl: int = DEFAULT_TOKEN_TTL) -> bool:
        """Extend the TTL of a token and update last accessed time.

        Args:
            token: The token string
            ttl: New TTL in seconds (default 2 hours)

        Returns:
            True if successful, False if token not found
        """
        r = await self._get_redis()

        play_token = await self.get_token(token)
        if not play_token:
            return False

        play_token.last_accessed_at = datetime.now(UTC)

        token_key = self._get_token_key(token)
        token_data_json = json.dumps(play_token.to_redis_dict())

        # Refresh TTL
        await r.set(token_key, token_data_json, ex=ttl)

        return True

    async def update_session_id(self, token: str, session_id: str) -> bool:
        """Update the session_id for a token.

        Args:
            token: The token string
            session_id: The transcoding session ID

        Returns:
            True if successful, False if token not found
        """
        r = await self._get_redis()

        play_token = await self.get_token(token)
        if not play_token:
            return False

        play_token.session_id = session_id
        play_token.last_accessed_at = datetime.now(UTC)

        token_key = self._get_token_key(token)
        token_data_json = json.dumps(play_token.to_redis_dict())

        # Get current TTL to preserve it
        ttl = await r.ttl(token_key)
        if ttl <= 0:
            ttl = DEFAULT_TOKEN_TTL

        await r.set(token_key, token_data_json, ex=ttl)

        return True

    async def delete_token(self, token: str) -> bool:
        """Delete a token from Redis.

        Args:
            token: The token string

        Returns:
            True if successful
        """
        r = await self._get_redis()

        token_key = self._get_token_key(token)

        # Remove from both key and set
        await r.delete(token_key)
        await r.srem(REDIS_TOKENS_SET, token)

        logger.info("Deleted play token: %s", _mask_token(token))

        return True

    async def get_all_tokens(self) -> list[PlayToken]:
        """Get all play tokens.

        Returns:
            List of all PlayTokens
        """
        r = await self._get_redis()

        token_strings = await r.smembers(REDIS_TOKENS_SET)
        tokens = []

        for token_str in token_strings:
            token = await self.get_token(token_str)
            if token:
                tokens.append(token)
            else:
                # Clean up stale token ID from set
                await r.srem(REDIS_TOKENS_SET, token_str)

        return tokens

    async def get_user_tokens(self, user_guid: str) -> list[PlayToken]:
        """Get all tokens for a specific user.

        Args:
            user_guid: The user GUID

        Returns:
            List of PlayTokens for the user
        """
        all_tokens = await self.get_all_tokens()
        return [t for t in all_tokens if t.user_guid == user_guid]


# Global service instance
_token_service: PlayTokenService | None = None


def get_play_token_service() -> PlayTokenService:
    """Get the global play token service instance."""
    global _token_service
    if _token_service is None:
        _token_service = PlayTokenService()
    return _token_service
