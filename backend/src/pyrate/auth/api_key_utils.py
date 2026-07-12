"""Shared API-key format, generation, and hashing helpers.

Single source of truth for the API-key wire format so the issuing router
(``api/v1/api_keys.py``) and the authenticating dependency
(``auth/dependencies.py``) can never diverge on prefix, length, or hash
algorithm — a divergence would silently invalidate previously issued keys.
"""

from __future__ import annotations

import hashlib
import secrets

# Human-recognisable prefix stored in plaintext on the key record and required
# on every presented raw key.
API_KEY_PREFIX = "pmak_"
# Length of the stored, non-secret ``key_prefix`` slice used for display/lookup.
API_KEY_PREFIX_LENGTH = 12


def generate_api_key() -> str:
    """Return a new raw API key (shown to the user exactly once)."""
    return f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"


def hash_api_key(raw_key: str) -> str:
    """Return the stored hash for a raw API key."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def api_key_display_prefix(raw_key: str) -> str:
    """Return the non-secret prefix stored alongside the hash for display."""
    return raw_key[:API_KEY_PREFIX_LENGTH]
