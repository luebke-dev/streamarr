"""httpOnly refresh-token cookie handling.

Web clients (browser SPA) keep only a short-lived access token in memory and
receive the long-lived refresh token as an httpOnly, Secure, SameSite cookie
that JavaScript cannot read — closing the localStorage XSS-exfiltration vector.

Native clients (Tauri desktop, Capacitor Android) send
``X-Client-Platform: native`` and keep receiving the refresh token in the JSON
body, since a webview/native store is their equivalent of the cookie jar and
the platforms manage credentials differently.

The switch is driven by the ``X-Client-Platform`` request header the frontend
sends. Absent header ⇒ body tokens (backward compatible for API scripts).
"""

from __future__ import annotations

from fastapi import Request, Response

from ..config import get_app_url

# Only sent to the auth endpoints that need it (refresh / logout), never to the
# rest of the API — narrows exposure and avoids bloating every request.
REFRESH_COOKIE_NAME = "pyrate_refresh"
# Scoped to the auth endpoints that consume it (refresh / logout). The API is
# mounted at /api, so the auth router lives at /api/auth.
REFRESH_COOKIE_PATH = "/api/auth"
# Matches the refresh-token lifetime (7 days).
_REFRESH_MAX_AGE = 7 * 24 * 60 * 60


def _cookie_secure() -> bool:
    """Secure cookies over HTTPS; relaxed on http:// dev origins so the cookie
    can still be set locally."""
    return get_app_url().lower().startswith("https://")


def client_wants_cookie(request: Request) -> bool:
    """True when the caller is the web SPA and should use the httpOnly cookie.

    Web sends ``X-Client-Platform: web``. Native sends ``native``; anything else
    (or absent) falls back to body tokens.
    """
    return request.headers.get("x-client-platform", "").strip().lower() == "web"


def set_refresh_cookie(response: Response, token: str) -> None:
    """Attach the refresh token as an httpOnly cookie."""
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        max_age=_REFRESH_MAX_AGE,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        path=REFRESH_COOKIE_PATH,
    )


def clear_refresh_cookie(response: Response) -> None:
    """Remove the refresh cookie (logout)."""
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
    )
