"""Authentication API Endpoints."""

import logging
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.dependencies import (
    get_current_user,
    get_current_user_optional,
    require_oidc_enabled,
    verify_refresh_token,
)
from ...auth.jwt_handler import jwt_handler
from ...auth.oidc_client import oidc_client
from ...auth.token_revocation import (
    mark_refresh_rotated,
    revoke_user_refresh_tokens,
)
from ...config import get_app_url, settings
from ...database import get_db_session
from ...models.user import User
from ...schemas.auth import (
    AuthStatus,
    BackgroundImageResponse,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserInfo,
)
from ...api.rate_limit import rate_limit
from ...schemas.invite import InviteUse
from ...schemas.user import LocalLoginRequest
from ...services.auth import AuthService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])

# 5 attempts per minute per IP is enough for a human but blocks credential
# stuffing and account-enumeration scripts. Applied to login and registration.
_auth_rate_limit = rate_limit(max_calls=5, window_seconds=60, scope="auth")
# Password-reset endpoints are slower to abuse but we still cap email floods.
_reset_rate_limit = rate_limit(max_calls=3, window_seconds=300, scope="auth-reset")

OIDC_STATE_TYPE = "oidc_state"
OIDC_STATE_TTL_MINUTES = 10


# ── ValueError → HTTPException mapping ──────────────────────────────────

_ERROR_MAP: dict[str, tuple[int, str]] = {
    # login
    "local_auth_disabled": (status.HTTP_501_NOT_IMPLEMENTED, "Local authentication is not enabled"),
    "invalid_credentials": (status.HTTP_401_UNAUTHORIZED, "Invalid email or password"),
    "no_local_password": (status.HTTP_401_UNAUTHORIZED, "User has no local password set. Please use OIDC login."),
    "user_inactive": (status.HTTP_401_UNAUTHORIZED, "User account is disabled"),
    "email_not_verified": (status.HTTP_403_FORBIDDEN, "Please verify your email address before logging in. Check your inbox for the verification link."),
    "open_registration_disabled": (status.HTTP_403_FORBIDDEN, "Open registration is not enabled. An invite is required."),
    # registration
    "invites_disabled": (status.HTTP_403_FORBIDDEN, "Invite system is disabled"),
    "invalid_email": (status.HTTP_400_BAD_REQUEST, "Invalid email address"),
    "weak_password": (status.HTTP_400_BAD_REQUEST, f"Password must be at least {settings.oidc.min_password_length} characters"),
    "name_required": (status.HTTP_400_BAD_REQUEST, "First name and last name are required"),
    "invalid_invite_token": (status.HTTP_400_BAD_REQUEST, "Invalid invite token"),
    "invite_invalid_or_expired": (status.HTTP_400_BAD_REQUEST, "Invite token is invalid, expired, or already used"),
    "email_exists": (status.HTTP_400_BAD_REQUEST, "User with this email already exists"),
    "invite_use_failed": (status.HTTP_400_BAD_REQUEST, "Invite could not be used"),
    # email verification
    "invalid_or_expired_token": (status.HTTP_400_BAD_REQUEST, "Invalid or expired verification link"),
    "invalid_token_payload": (status.HTTP_400_BAD_REQUEST, "Invalid verification token"),
    "user_not_found": (status.HTTP_404_NOT_FOUND, "User not found"),
    "email_mismatch": (status.HTTP_400_BAD_REQUEST, "Verification link does not match current email address"),
    "send_failed": (status.HTTP_503_SERVICE_UNAVAILABLE, "Failed to send verification email. Please try again later."),
    # OIDC
    "missing_oidc_sub": (status.HTTP_400_BAD_REQUEST, "Missing OIDC subject identifier"),
    "registration_disabled": (status.HTTP_403_FORBIDDEN, "User registration is disabled"),
    "email_required": (status.HTTP_400_BAD_REQUEST, "Email is required for user creation"),
    "oidc_email_unverified": (status.HTTP_403_FORBIDDEN, "The identity provider did not verify this email address, so it cannot be linked to an existing account."),
}


def _raise_for_value_error(e: ValueError) -> None:
    """Convert a service ValueError to an HTTPException."""
    code = str(e)
    status_code, detail = _ERROR_MAP.get(code, (status.HTTP_400_BAD_REQUEST, code))
    raise HTTPException(status_code=status_code, detail=detail)


def _safe_return_to(value: str | None) -> str:
    if not value or not value.startswith("/") or value.startswith("//"):
        return "/"
    return value


def _create_oidc_state(return_to: str | None = None) -> tuple[str, str]:
    nonce = secrets.token_urlsafe(32)
    payload = {
        "type": OIDC_STATE_TYPE,
        "nonce": nonce,
        "return_to": _safe_return_to(return_to),
        "jti": secrets.token_urlsafe(16),
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(minutes=OIDC_STATE_TTL_MINUTES),
    }
    token = jwt.encode(payload, settings.secret_key, algorithm="HS256")
    return token, nonce


def _verify_oidc_state(state: str | None) -> dict:
    if not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Missing state parameter"
        )
    try:
        payload = jwt.decode(state, settings.secret_key, algorithms=["HS256"])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid state parameter"
        )
    if payload.get("type") != OIDC_STATE_TYPE or not payload.get("nonce"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid state parameter"
        )
    payload["return_to"] = _safe_return_to(payload.get("return_to"))
    return payload


# ── Routes ──────────────────────────────────────────────────────────────


@router.get("/status", response_model=AuthStatus)
async def get_auth_status(
    current_user: User | None = Depends(get_current_user_optional),
):
    """Return the current authentication status."""
    user_info = None
    if current_user:
        user_info = UserInfo(
            guid=str(current_user.guid),
            email=current_user.email,
            first_name=current_user.first_name,
            last_name=current_user.last_name,
            preferred_username=current_user.preferred_username,
            picture=current_user.picture,
            is_active=current_user.is_active,
            is_superuser=current_user.is_superuser,
            email_verified=current_user.email_verified,
            last_login=current_user.last_login,
            ui_language=current_user.ui_language,
            audio_languages=current_user.audio_languages,
            subtitle_language=current_user.subtitle_language,
            allowed_libraries=current_user.allowed_libraries,
        )

    auth_methods = []
    if oidc_client.is_enabled():
        auth_methods.append("oidc")
    if settings.oidc.local_auth_enabled:
        auth_methods.append("local")

    return AuthStatus(
        authenticated=current_user is not None,
        user=user_info,
        oidc_enabled=oidc_client.is_enabled(),
        local_auth_enabled=settings.oidc.local_auth_enabled,
        open_registration=settings.oidc.open_registration,
        auth_methods=auth_methods,
    )


@router.get("/background", response_model=BackgroundImageResponse)
async def get_background_image(session: AsyncSession = Depends(get_db_session)):
    """Returns a random media item backdrop URL and title for the login/register pages."""
    return await AuthService(session).get_random_background()


@router.get("/login")
async def login(return_to: str | None = None):
    """Startet den OIDC Login Flow"""
    require_oidc_enabled()

    state, nonce = _create_oidc_state(return_to=return_to)
    auth_url = await oidc_client.get_authorization_url(state, nonce=nonce)
    return RedirectResponse(url=auth_url)


@router.get("/callback")
async def auth_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    session: AsyncSession = Depends(get_db_session),
):
    """OIDC Callback Handler"""
    require_oidc_enabled()

    frontend_url = get_app_url()
    callback_url = f"{frontend_url}/auth/callback"

    if error:
        error_query = quote(error_description or error, safe="")
        return RedirectResponse(url=f"{callback_url}?error={error_query}")

    state_payload = _verify_oidc_state(state)
    stored_nonce = state_payload["nonce"]
    return_to = state_payload.get("return_to") or "/"

    if not code:
        return RedirectResponse(url=f"{callback_url}?error=missing_code")

    try:
        token_response = await oidc_client.exchange_code_for_tokens(code, state or "")

        id_token = token_response.get("id_token")
        if id_token:
            id_claims = await oidc_client.verify_id_token(
                id_token, nonce=stored_nonce
            )
        else:
            access_token = token_response["access_token"]
            id_claims = await oidc_client.get_userinfo(access_token)

        user_data = oidc_client.map_claims_to_user_data(id_claims)

        auth_service = AuthService(session)
        try:
            user = await auth_service.get_or_create_oidc_user(user_data)
        except ValueError as e:
            _raise_for_value_error(e)

        access_token, refresh_token, _ = auth_service._create_token_pair(user)

        redirect_url = (
            f"{callback_url}?return_to={quote(return_to, safe='/')}"
            f"#access_token={access_token}&refresh_token={refresh_token}"
        )
        return RedirectResponse(url=redirect_url)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("OIDC callback failed: %s", e, exc_info=True)
        error_url = f"{callback_url}?error=authentication_failed"
        return RedirectResponse(url=error_url)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(user_and_jti: tuple[User, str] = Depends(verify_refresh_token)):
    """Erneuert einen Access Token mit einem Refresh Token"""
    user, jti = user_and_jti

    # Single-use rotation: retire the presented refresh token so it can't be
    # replayed, then issue a fresh pair.
    await mark_refresh_rotated(jti)

    token_data = {"sub": str(user.guid)}
    access_token = jwt_handler.create_access_token(token_data)
    new_refresh_token = jwt_handler.create_refresh_token(token_data)

    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        expires_in=settings.oidc.jwt_access_token_expire_minutes * 60,
    )


@router.post("/logout")
async def logout(request: Request, current_user: User = Depends(get_current_user)):
    """Loggt den Benutzer aus"""
    # Revoke the user's outstanding refresh tokens server-side so a leaked one
    # can't keep minting access tokens after logout. Access tokens already held
    # remain valid until their short natural expiry.
    await revoke_user_refresh_tokens(current_user.guid)

    if oidc_client.is_enabled():
        logout_url = await oidc_client.get_logout_url()
        return {"logout_url": logout_url}
    else:
        return {"message": "Logged out successfully"}


@router.post(
    "/local/login",
    response_model=TokenResponse,
    dependencies=[Depends(_auth_rate_limit)],
)
async def local_login(
    request: Request,
    login_data: LocalLoginRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Lokale Benutzeranmeldung mit Email und Passwort"""
    auth_service = AuthService(session)
    try:
        user, access_token, refresh_token, expires_in = await auth_service.local_login(
            email=login_data.email,
            password=login_data.password,
            device_id=login_data.device_id,
            device_info=login_data.device_info,
            client_ip=request.client.host if request.client else None,
        )
    except ValueError as e:
        _raise_for_value_error(e)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    dependencies=[Depends(_auth_rate_limit)],
)
async def register_with_invite(
    registration_data: InviteUse, session: AsyncSession = Depends(get_db_session)
):
    """Register a new user with an invite token."""
    auth_service = AuthService(session)
    try:
        user, access_token, refresh_token, expires_in = await auth_service.register_with_invite(
            email=registration_data.email,
            password=registration_data.password,
            first_name=registration_data.first_name,
            last_name=registration_data.last_name,
            invite_token=registration_data.invite_token,
            preferred_username=registration_data.preferred_username,
            ui_language=registration_data.ui_language,
            audio_languages=registration_data.audio_languages,
            subtitle_language=registration_data.subtitle_language,
        )
    except ValueError as e:
        _raise_for_value_error(e)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
    )


class OpenRegistration(BaseModel):
    email: str
    password: str | None = None
    first_name: str
    last_name: str
    preferred_username: str | None = None
    ui_language: str | None = None
    audio_languages: list[str] | None = None
    subtitle_language: str | None = None


@router.post(
    "/register/open",
    response_model=TokenResponse,
    dependencies=[Depends(_auth_rate_limit)],
)
async def register_open(
    data: OpenRegistration, session: AsyncSession = Depends(get_db_session)
):
    """Register a new user without an invite (open registration)."""
    auth_service = AuthService(session)
    try:
        user, access_token, refresh_token, expires_in = await auth_service.register_open(
            email=data.email,
            password=data.password,
            first_name=data.first_name,
            last_name=data.last_name,
            preferred_username=data.preferred_username,
            ui_language=data.ui_language,
            audio_languages=data.audio_languages,
            subtitle_language=data.subtitle_language,
        )
    except ValueError as e:
        _raise_for_value_error(e)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
    )


@router.get("/verify-email")
async def verify_email(
    token: str,
    session: AsyncSession = Depends(get_db_session),
):
    """Verify a user's email address using the token from the verification email."""
    auth_service = AuthService(session)
    try:
        return await auth_service.verify_email(token)
    except ValueError as e:
        _raise_for_value_error(e)


@router.post("/resend-verification")
async def resend_verification_email(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Resend the email verification link to the current user."""
    auth_service = AuthService(session)
    try:
        return await auth_service.resend_verification_email(current_user)
    except ValueError as e:
        _raise_for_value_error(e)


@router.post("/forgot-password", dependencies=[Depends(_reset_rate_limit)])
async def forgot_password(
    body: ForgotPasswordRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Request a password reset email."""
    auth_service = AuthService(session)
    try:
        return await auth_service.request_password_reset(body.email)
    except ValueError as e:
        _raise_for_value_error(e)


@router.post("/reset-password", dependencies=[Depends(_reset_rate_limit)])
async def reset_password(
    body: ResetPasswordRequest,
    session: AsyncSession = Depends(get_db_session),
):
    """Reset a user's password using a valid reset token."""
    auth_service = AuthService(session)
    try:
        return await auth_service.reset_password(body.token, body.password)
    except ValueError as e:
        _raise_for_value_error(e)


@router.get("/me", response_model=UserInfo)
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """Return information about the current user."""
    return UserInfo(
        guid=str(current_user.guid),
        email=current_user.email,
        first_name=current_user.first_name,
        last_name=current_user.last_name,
        preferred_username=current_user.preferred_username,
        picture=current_user.picture,
        is_active=current_user.is_active,
        is_superuser=current_user.is_superuser,
        last_login=current_user.last_login,
        ui_language=current_user.ui_language,
        audio_languages=current_user.audio_languages,
        subtitle_language=current_user.subtitle_language,
    )
