"""OIDC client for OpenID Connect authentication."""

import json
import logging
import time
from typing import Any
from urllib.parse import urlencode

import httpx
from authlib.integrations.httpx_client import AsyncOAuth2Client
from authlib.oidc.core import CodeIDToken

from ..config import settings

logger = logging.getLogger(__name__)


class OIDCClient:
    """OIDC client for authenticating with OpenID Connect providers."""

    def __init__(self):
        self._uses_runtime_settings = True
        self.config = settings.oidc
        self.client_id = self.config.client_id
        self.client_secret = self.config.client_secret
        self.redirect_uri = self.config.redirect_uri
        self.scopes = " ".join(self.config.scopes)

        # Provider metadata
        self._metadata: dict[str, Any] | None = None
        self._jwks: dict[str, Any] | None = None
        self._jwks_loaded_at = 0.0
        self._jwks_ttl_seconds = 300

    def _refresh_config(self) -> None:
        """Refresh import-time convenience attributes from runtime settings."""
        if not getattr(self, "_uses_runtime_settings", False):
            return
        self.config = settings.oidc
        self.client_id = self.config.client_id
        self.client_secret = self.config.client_secret
        self.redirect_uri = self.config.redirect_uri
        self.scopes = " ".join(self.config.scopes)

    @staticmethod
    def _validate_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
        required = ["issuer", "authorization_endpoint", "token_endpoint", "jwks_uri"]
        missing = [key for key in required if not metadata.get(key)]
        if missing:
            raise ValueError(f"OIDC provider metadata missing: {', '.join(missing)}")
        return metadata

    async def get_provider_metadata(self) -> dict[str, Any]:
        """Load provider metadata from the well-known URL."""
        self._refresh_config()
        if self._metadata:
            return self._metadata

        if not self.config.server_metadata_url:
            # Fall back to manual configuration.
            self._metadata = {
                "issuer": self.config.issuer,
                "authorization_endpoint": self.config.authorization_endpoint,
                "token_endpoint": self.config.token_endpoint,
                "userinfo_endpoint": self.config.userinfo_endpoint,
                "jwks_uri": self.config.jwks_uri,
                "end_session_endpoint": self.config.end_session_endpoint,
            }
            return self._validate_metadata(self._metadata)

        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            response = await client.get(self.config.server_metadata_url)
            response.raise_for_status()
            self._metadata = self._validate_metadata(response.json())

        return self._metadata

    async def get_authorization_url(self, state: str, nonce: str | None = None) -> str:
        """Build the authorization URL for the OIDC flow.

        ``nonce`` is bound into the request so ``verify_id_token`` can reject a
        replayed ID token that doesn't carry the same value back.
        """
        metadata = await self.get_provider_metadata()

        params = {
            "response_type": "code",
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "scope": " ".join(self.config.scopes),
            "state": state,
        }
        if nonce:
            params["nonce"] = nonce

        auth_endpoint = metadata["authorization_endpoint"]
        return f"{auth_endpoint}?{urlencode(params)}"

    async def exchange_code_for_tokens(self, code: str, state: str) -> dict[str, Any]:
        """Exchange the authorization code for tokens."""
        metadata = await self.get_provider_metadata()

        client = AsyncOAuth2Client(
            client_id=self.config.client_id,
            client_secret=self.config.client_secret,
        )

        token_response = await client.fetch_token(
            metadata["token_endpoint"],
            code=code,
            redirect_uri=self.config.redirect_uri,
        )

        return token_response

    async def get_userinfo(self, access_token: str) -> dict[str, Any]:
        """Fetch user info from the provider."""
        metadata = await self.get_provider_metadata()

        headers = {"Authorization": f"Bearer {access_token}"}

        async with httpx.AsyncClient() as client:
            response = await client.get(metadata["userinfo_endpoint"], headers=headers)
            response.raise_for_status()
        return response.json()

    async def _get_jwks(self, jwks_uri: str) -> dict[str, Any]:
        now = time.monotonic()
        jwks = getattr(self, "_jwks", None)
        loaded_at = getattr(self, "_jwks_loaded_at", 0.0)
        ttl = getattr(self, "_jwks_ttl_seconds", 300)
        if jwks and now - loaded_at < ttl:
            return jwks

        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            jwks_response = await client.get(jwks_uri)
            jwks_response.raise_for_status()
            self._jwks = jwks_response.json()
            self._jwks_loaded_at = now
            return self._jwks

    async def verify_id_token(
        self, id_token: str, nonce: str | None = None
    ) -> dict[str, Any]:
        """Verify the ID token.

        Validates signature, ``iss`` and ``aud`` via authlib's ``CodeIDToken``.
        When ``nonce`` is provided, checks that it matches the token's claim
        (replay protection — the authorization request should always include
        the same nonce).
        """
        metadata = await self.get_provider_metadata()

        jwks = await self._get_jwks(metadata["jwks_uri"])

        # Verify the ID token.
        claims = CodeIDToken.parse(
            id_token,
            key=jwks,
            issuer=metadata["issuer"],
            audience=self.config.client_id,
        )

        if nonce is not None:
            token_nonce = claims.get("nonce")
            if token_nonce != nonce:
                logger.warning(
                    "OIDC id_token nonce mismatch: expected present, got %s",
                    "set" if token_nonce else "missing",
                )
                raise ValueError("OIDC id_token nonce mismatch")

        logger.debug(
            "OIDC id_token verified (iss=%s, sub=%s)",
            claims.get("iss"), claims.get("sub"),
        )
        return claims

    async def get_logout_url(self, id_token_hint: str | None = None) -> str:
        """Build the logout URL."""
        metadata = await self.get_provider_metadata()

        params = {
            "post_logout_redirect_uri": self.config.post_logout_redirect_uri,
        }

        if id_token_hint:
            params["id_token_hint"] = id_token_hint

        end_session_endpoint = metadata.get("end_session_endpoint")
        if not end_session_endpoint:
            # Fallback for providers without an end-session endpoint.
            return self.config.post_logout_redirect_uri

        return f"{end_session_endpoint}?{urlencode(params)}"

    def map_claims_to_user_data(self, claims: dict[str, Any]) -> dict[str, Any]:
        """Map OIDC claims to local user data."""
        self._refresh_config()
        user_data = {}

        for oidc_claim, local_field in self.config.claim_mapping.items():
            if oidc_claim in claims:
                value = claims[oidc_claim]

                # Groups need to be stored as a JSON string.
                if local_field == "groups" and isinstance(value, (list, dict)):
                    value = json.dumps(value)

                user_data[local_field] = value

        if claims.get("iss") and "oidc_provider" not in user_data:
            user_data["oidc_provider"] = claims["iss"]

        return user_data

    def is_enabled(self) -> bool:
        """Whether OIDC is enabled and configured."""
        self._refresh_config()
        return (
            self.config.enabled
            and self.config.client_id
            and self.config.client_secret
            and (self.config.server_metadata_url or self.config.issuer)
        )


# Global instance.
oidc_client = OIDCClient()
