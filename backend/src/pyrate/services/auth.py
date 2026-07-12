"""
Auth Service

Handles authentication business logic: local login, registration,
email verification, password reset, and OIDC user management.
"""

import logging
import uuid as uuid_mod
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.auth.jwt_handler import jwt_handler
from pyrate.config import get_app_url, settings
from pyrate.models.user import User
from pyrate.services.email import email_service

logger = logging.getLogger(__name__)

# A fixed, valid password hash used to spend the same PBKDF2 work on the
# unknown-email / no-local-password paths as on a real verification, so login
# response timing doesn't reveal whether an account exists. Computed once.
_DUMMY_PASSWORD_HASH = jwt_handler.get_password_hash("timing-equalizer-not-a-secret")

# ── Email i18n strings ──────────────────────────────────────────────────

EMAIL_I18N: dict[str, dict[str, dict[str, str]]] = {
    "welcome": {
        "en": {
            "subject": "Welcome to {app_name}",
            "heading": "Welcome, {user_name}!",
            "body": "Thanks for signing up at {app_name}. Your account has been created successfully!",
            "features": "You can now access your media library and enjoy all the great features {app_name} has to offer.",
            "button": "Log in now",
            "help": "If you have any questions or need help, don't hesitate to reach out.",
        },
        "de": {
            "subject": "Willkommen bei {app_name}",
            "heading": "Willkommen, {user_name}!",
            "body": "Vielen Dank für Ihre Registrierung bei {app_name}. Ihr Account wurde erfolgreich erstellt!",
            "features": "Sie können jetzt auf Ihre Medienbibliothek zugreifen und all die großartigen Funktionen nutzen, die {app_name} zu bieten hat.",
            "button": "Jetzt anmelden",
            "help": "Falls Sie Fragen haben oder Hilfe benötigen, zögern Sie nicht, sich an uns zu wenden.",
        },
    },
    "notification": {
        "en": {
            "footer": "This email was sent automatically by {app_name}.",
            "ignore_hint": "If you did not request this email, you can safely ignore it.",
        },
        "de": {
            "footer": "Diese E-Mail wurde automatisch von {app_name} gesendet.",
            "ignore_hint": "Falls Sie diese E-Mail nicht angefordert haben, können Sie sie ignorieren.",
        },
    },
    "verify_email": {
        "en": {
            "subject": "Verify your email — {app_name}",
            "heading": "Verify your email address",
            "greeting": "Hi",
            "body": "Thanks for signing up! Please confirm your email address by clicking the button below:",
            "button": "Verify Email",
            "link_hint": "If the button doesn't work, copy and paste this link into your browser:",
            "expiry_note": "This link expires in 24 hours. If you didn't create an account, you can safely ignore this email.",
        },
        "de": {
            "subject": "E-Mail bestätigen — {app_name}",
            "heading": "E-Mail-Adresse bestätigen",
            "greeting": "Hallo",
            "body": "Vielen Dank für Ihre Registrierung! Bitte bestätigen Sie Ihre E-Mail-Adresse mit einem Klick auf den Button:",
            "button": "E-Mail bestätigen",
            "link_hint": "Falls der Button nicht funktioniert, kopieren Sie diesen Link in Ihren Browser:",
            "expiry_note": "Dieser Link ist 24 Stunden gültig. Falls Sie kein Konto erstellt haben, können Sie diese E-Mail ignorieren.",
        },
    },
    "password_reset": {
        "en": {
            "subject": "Reset your password — {app_name}",
            "heading": "Reset your password",
            "greeting": "Hi",
            "body": "We received a request to reset your password. Click the button below to choose a new password:",
            "button": "Reset Password",
            "link_hint": "If the button doesn't work, copy and paste this link into your browser:",
            "expiry_note": "This link expires in 1 hour. If you didn't request a password reset, you can safely ignore this email.",
        },
        "de": {
            "subject": "Passwort zurücksetzen — {app_name}",
            "heading": "Passwort zurücksetzen",
            "greeting": "Hallo",
            "body": "Wir haben eine Anfrage zum Zurücksetzen Ihres Passworts erhalten. Klicken Sie auf den Button, um ein neues Passwort festzulegen:",
            "button": "Passwort zurücksetzen",
            "link_hint": "Falls der Button nicht funktioniert, kopieren Sie diesen Link in Ihren Browser:",
            "expiry_note": "Dieser Link ist 1 Stunde gültig. Falls Sie kein Zurücksetzen angefordert haben, können Sie diese E-Mail ignorieren.",
        },
    },
}


def _get_email_i18n(template_key: str, user: User) -> dict[str, str]:
    """Get i18n strings for an email template based on user language."""
    lang = (user.ui_language or "en-US")[:2].lower()
    strings = EMAIL_I18N.get(template_key, {})
    return strings.get(lang, strings.get("en", {}))


def _get_app_url() -> str:
    """Get the public-facing app URL for outbound email links.

    Thin wrapper around `config.get_app_url()` — kept as a module-level
    helper because several places in this file call it.
    """
    return get_app_url()


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Helpers ──────────────────────────────────────────────────────────

    async def _get_site_name(self) -> str:
        """Load site name from DB settings, fallback to 'Pyrate Media'."""
        from pyrate.services.settings import SettingsService

        try:
            return await SettingsService(self.db).get("system.site_name", "Pyrate Media")
        except Exception:
            return "Pyrate Media"

    async def _send_welcome_email(self, user: User, app_name: str = "Pyrate Media") -> bool:
        """Send a welcome email to a newly registered user."""
        i18n_raw = _get_email_i18n("welcome", user)
        lang = (user.ui_language or "en-US")[:2].lower()
        user_name = user.first_name or user.email

        # Replace placeholders in i18n strings
        i18n = {
            k: v.replace("{app_name}", app_name).replace("{user_name}", user_name)
            for k, v in i18n_raw.items()
        }
        subject = i18n.get("subject", f"Welcome to {app_name}")

        app_url = _get_app_url()
        context = {
            "user_name": user_name,
            "app_name": app_name,
            "app_url": app_url,
            "subject": subject,
            "lang": lang,
            "i18n": i18n,
        }

        sent = await email_service.send_email(
            to_email=user.email,
            subject=subject,
            template_name="welcome",
            context=context,
        )

        if not sent:
            logger.warning("Failed to send welcome email to %s", user.email)

        return sent

    async def _send_verification_email(self, user: User, app_name: str = "Pyrate Media") -> bool:
        """Generate a verification token and send the verification email."""
        token = jwt_handler.create_email_verify_token(
            user_id=str(user.guid),
            email=user.email,
        )

        app_url = _get_app_url()
        i18n_raw = _get_email_i18n("verify_email", user)
        lang = (user.ui_language or "en-US")[:2].lower()

        # Replace {app_name} placeholder in i18n strings
        i18n = {k: v.replace("{app_name}", app_name) for k, v in i18n_raw.items()}
        subject = i18n.get("subject", f"Verify your email — {app_name}")

        context = {
            "user_name": user.first_name or user.email,
            "verify_url": f"{app_url}/auth/verify-email?token={token}",
            "app_name": app_name,
            "app_url": app_url,
            "subject": subject,
            "lang": lang,
            "i18n": i18n,
        }

        sent = await email_service.send_email(
            to_email=user.email,
            subject=subject,
            template_name="verify_email",
            context=context,
        )

        if not sent:
            logger.warning("Failed to send verification email to %s", user.email)

        return sent

    async def _send_password_reset_email(self, user: User, app_name: str = "Pyrate Media") -> bool:
        """Generate a reset token and send the password reset email."""
        token = jwt_handler.create_password_reset_token(
            user_id=str(user.guid),
            email=user.email,
            password_hash=user.hashed_password,
        )

        app_url = _get_app_url()
        i18n_raw = _get_email_i18n("password_reset", user)
        lang = (user.ui_language or "en-US")[:2].lower()

        # Replace {app_name} placeholder in i18n strings
        i18n = {k: v.replace("{app_name}", app_name) for k, v in i18n_raw.items()}
        subject = i18n.get("subject", f"Reset your password — {app_name}")

        context = {
            "user_name": user.first_name or user.email,
            "reset_url": f"{app_url}/auth/reset-password?token={token}",
            "app_name": app_name,
            "app_url": app_url,
            "subject": subject,
            "lang": lang,
            "i18n": i18n,
        }

        sent = await email_service.send_email(
            to_email=user.email,
            subject=subject,
            template_name="password_reset",
            context=context,
        )

        if sent:
            logger.info("Password reset email sent to %s", user.email)
        else:
            logger.warning("Failed to send password reset email to %s", user.email)

        return sent

    def _create_token_pair(
        self, user: User, device_id: str | None = None
    ) -> tuple[str, str, int]:
        """Create access + refresh tokens. Returns (access_token, refresh_token, expires_in)."""
        token_data: dict[str, Any] = {"sub": str(user.guid)}
        if device_id:
            token_data["device_id"] = device_id

        access_token = jwt_handler.create_access_token(token_data)
        refresh_token = jwt_handler.create_refresh_token(token_data)
        expires_in = settings.oidc.jwt_access_token_expire_minutes * 60
        return access_token, refresh_token, expires_in

    # ── Background Image ─────────────────────────────────────────────────

    async def get_random_background(self) -> dict[str, Any]:
        """Return a random media backdrop for the login page."""
        from pyrate.models.media import MediaItem

        result = await self.db.execute(
            select(MediaItem.backdrop_path, MediaItem.title, MediaItem.release_date)
            .where(MediaItem.backdrop_path.isnot(None))
            .order_by(func.random())
            .limit(1)
        )
        row = result.one_or_none()
        if not row:
            return {"url": None, "title": None, "year": None}
        backdrop_path, title, release_date = row
        year = release_date.year if release_date else None
        return {
            "url": f"https://image.tmdb.org/t/p/original{backdrop_path}",
            "title": title,
            "year": year,
        }

    # ── Local Login ──────────────────────────────────────────────────────

    async def local_login(
        self,
        email: str,
        password: str,
        device_id: str | None = None,
        device_info: dict | None = None,
        client_ip: str | None = None,
    ) -> tuple[User, str, str, int]:
        """
        Authenticate a local user.
        Returns (user, access_token, refresh_token, expires_in).

        Raises ValueError with codes:
            "local_auth_disabled", "invalid_credentials",
            "no_local_password", "user_inactive"
        """
        logger.debug("Local login attempt for %s from %s", email, client_ip or "-")

        if not settings.oidc.local_auth_enabled:
            logger.warning("Local login refused: local auth disabled (email=%s)", email)
            raise ValueError("local_auth_disabled")

        stmt = select(User).where(User.email == email)
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            # Don't leak account existence at WARN; INFO is enough for ops.
            # Spend the same hashing work as a real verify so the response time
            # doesn't distinguish unknown emails from registered ones, and use
            # the same generic error code.
            jwt_handler.verify_password(password, _DUMMY_PASSWORD_HASH)
            logger.info("Local login failed (unknown email) email=%s ip=%s", email, client_ip or "-")
            raise ValueError("invalid_credentials")

        if not user.hashed_password:
            # Account exists but is OIDC-only. Don't reveal that distinction:
            # equalize timing and return the same generic error as a bad
            # password / unknown email.
            jwt_handler.verify_password(password, _DUMMY_PASSWORD_HASH)
            logger.info("Local login refused (no local password) user=%s", user.guid)
            raise ValueError("invalid_credentials")

        if not jwt_handler.verify_password(password, user.hashed_password):
            logger.warning(
                "Local login failed (bad password) user=%s ip=%s",
                user.guid, client_ip or "-",
            )
            raise ValueError("invalid_credentials")

        if not user.is_active:
            logger.warning("Local login refused (user inactive) user=%s", user.guid)
            raise ValueError("user_inactive")

        if not user.email_verified:
            logger.info("Local login refused (email not verified) user=%s", user.guid)
            raise ValueError("email_not_verified")

        # Update last login
        user.last_login = datetime.now(UTC)
        await self.db.commit()

        # Create/update device if provided
        if device_id:
            from pyrate.services.device import DeviceService

            await DeviceService(self.db).get_or_create_device(
                user_id=user.guid,
                device_id=device_id,
                device_info=device_info,
                ip_address=client_ip,
            )

        access_token, refresh_token, expires_in = self._create_token_pair(user, device_id)
        logger.info(
            "Local login success user=%s email=%s device=%s ip=%s",
            user.guid, user.email, device_id or "-", client_ip or "-",
        )
        return user, access_token, refresh_token, expires_in

    # ── Registration ─────────────────────────────────────────────────────

    @staticmethod
    def _validate_registration_input(
        email: str, password: str | None, first_name: str, last_name: str
    ) -> str:
        """
        Validate registration fields. Returns the normalised email.

        Raises ValueError with codes:
            "invalid_email", "weak_password", "name_required"
        """
        email = email.strip().lower()
        if not email or "@" not in email or len(email) > 254:
            raise ValueError("invalid_email")

        if password and settings.oidc.local_auth_enabled:
            from pyrate.auth.password import validate_password_strength
            validate_password_strength(password)

        if not first_name.strip() or not last_name.strip():
            raise ValueError("name_required")

        return email

    async def _validate_and_consume_invite(self, invite_token: str, email: str):
        """
        Verify the invite token, check for duplicate email, and mark the
        invite as used.

        Returns (invite, invite_result).

        Raises ValueError with codes:
            "invalid_invite_token", "invite_invalid_or_expired",
            "email_exists", "invite_use_failed"
        """
        from pyrate.services.invite import InviteService

        invite_data = jwt_handler.verify_invite_token(invite_token)
        if not invite_data:
            raise ValueError("invalid_invite_token")

        invite_service = InviteService(self.db)
        invite = await invite_service.get_valid_by_token(invite_token)
        if not invite:
            raise ValueError("invite_invalid_or_expired")

        # Check duplicate email
        stmt = select(User).where(func.lower(User.email) == email)
        result = await self.db.execute(stmt)
        if result.scalar_one_or_none():
            raise ValueError("email_exists")

        # Atomically consume one use. use_invite() performs a guarded UPDATE, so
        # a concurrent registration that raced past get_valid_by_token above
        # loses here (rowcount 0 -> None) and is rejected as exhausted.
        invite_result = await invite_service.use_invite(invite.guid, None)
        if not invite_result:
            raise ValueError("invite_use_failed")

        return invite, invite_result

    async def _create_registered_user(
        self,
        email: str,
        password: str | None,
        first_name: str,
        last_name: str,
        preferred_username: str | None,
        ui_language: str | None,
        audio_languages: list[str] | None,
        subtitle_language: str | None,
    ) -> User:
        """Create and persist a new locally-registered user."""
        new_user = User(
            email=email,
            first_name=first_name.strip(),
            last_name=last_name.strip(),
            preferred_username=preferred_username,
            is_active=True,
            is_superuser=False,
            last_login=datetime.now(UTC),
            ui_language=ui_language or "en-US",
            audio_languages=audio_languages or ["en"],
            subtitle_language=subtitle_language,
        )

        if password and settings.oidc.local_auth_enabled:
            new_user.hashed_password = jwt_handler.get_password_hash(password)

        self.db.add(new_user)
        try:
            await self.db.commit()
        except IntegrityError:
            # Unique-constraint on ``email`` — two concurrent registrations
            # raced and the pre-check both passed. Rollback + translate to
            # the same ValueError code as the pre-check.
            await self.db.rollback()
            logger.info("Concurrent registration collided on email=%s", email)
            raise ValueError("email_exists")
        await self.db.refresh(new_user)
        return new_user

    async def _link_invite_and_befriend(self, invite, invite_result, new_user: User) -> None:
        """Link the invite to the new user and auto-befriend with the inviter."""
        from pyrate.services.friendship import FriendshipService

        invite_result.used_by_user_id = new_user.guid
        await self.db.commit()

        if invite.created_by_user_id:
            try:
                await FriendshipService(self.db).create_accepted(
                    user_a_id=invite.created_by_user_id,
                    user_b_id=new_user.guid,
                )
            except Exception as e:
                logger.warning("Failed to auto-befriend with inviter: %s", e)

    async def register_with_invite(
        self,
        email: str,
        password: str | None,
        first_name: str,
        last_name: str,
        invite_token: str,
        preferred_username: str | None = None,
        ui_language: str | None = None,
        audio_languages: list[str] | None = None,
        subtitle_language: str | None = None,
    ) -> tuple[User, str, str, int]:
        """
        Register a new user with an invite token.
        Returns (user, access_token, refresh_token, expires_in).

        Raises ValueError with codes:
            "invites_disabled", "invalid_email", "weak_password",
            "name_required", "invalid_invite_token",
            "invite_invalid_or_expired", "email_exists", "invite_use_failed"
        """
        if not settings.invites.enabled:
            raise ValueError("invites_disabled")

        email = self._validate_registration_input(email, password, first_name, last_name)
        invite, invite_result = await self._validate_and_consume_invite(invite_token, email)

        new_user = await self._create_registered_user(
            email, password, first_name, last_name,
            preferred_username, ui_language, audio_languages, subtitle_language,
        )

        await self._link_invite_and_befriend(invite, invite_result, new_user)

        access_token, refresh_token, expires_in = self._create_token_pair(new_user)
        logger.info("New user registered: %s (invited by %s)", email, invite.created_by_user_id)

        # Send welcome & verification emails (non-blocking)
        app_name = await self._get_site_name()
        await self._send_welcome_email(new_user, app_name=app_name)
        await self._send_verification_email(new_user, app_name=app_name)

        return new_user, access_token, refresh_token, expires_in

    async def register_open(
        self,
        email: str,
        password: str | None,
        first_name: str,
        last_name: str,
        preferred_username: str | None = None,
        ui_language: str | None = None,
        audio_languages: list[str] | None = None,
        subtitle_language: str | None = None,
    ) -> tuple[User, str, str, int]:
        """
        Register a new user without an invite (open registration).
        Returns (user, access_token, refresh_token, expires_in).

        Raises ValueError with codes:
            "open_registration_disabled", "invalid_email", "weak_password",
            "name_required", "email_exists"
        """
        if not settings.oidc.open_registration:
            raise ValueError("open_registration_disabled")

        email = self._validate_registration_input(email, password, first_name, last_name)

        # Check duplicate email
        stmt = select(User).where(func.lower(User.email) == email)
        result = await self.db.execute(stmt)
        if result.scalar_one_or_none():
            raise ValueError("email_exists")

        new_user = await self._create_registered_user(
            email, password, first_name, last_name,
            preferred_username, ui_language, audio_languages, subtitle_language,
        )

        access_token, refresh_token, expires_in = self._create_token_pair(new_user)
        logger.info("New user registered (open): %s", email)

        # Send welcome & verification emails (non-blocking)
        app_name = await self._get_site_name()
        await self._send_welcome_email(new_user, app_name=app_name)
        await self._send_verification_email(new_user, app_name=app_name)

        return new_user, access_token, refresh_token, expires_in

    # ── Email Verification ───────────────────────────────────────────────

    async def verify_email(self, token: str) -> dict[str, str]:
        """
        Verify a user's email using a verification token.
        Returns {"message": "..."}.

        Raises ValueError with codes:
            "invalid_or_expired_token", "invalid_token_payload",
            "user_not_found", "email_mismatch"
        """
        payload = jwt_handler.verify_email_verify_token(token)
        if not payload:
            raise ValueError("invalid_or_expired_token")

        user_id = payload.get("sub")
        token_email = payload.get("email")
        if not user_id or not token_email:
            raise ValueError("invalid_token_payload")

        stmt = select(User).where(User.guid == uuid_mod.UUID(user_id))
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            raise ValueError("user_not_found")

        if user.email_verified:
            return {"message": "Email already verified"}

        if user.email.lower() != token_email.lower():
            raise ValueError("email_mismatch")

        user.email_verified = True
        await self.db.commit()

        logger.info("Email verified for user %s (%s)", user.guid, user.email)
        return {"message": "Email verified successfully"}

    async def resend_verification_email(self, user: User) -> dict[str, str]:
        """
        Resend email verification to user. Returns {"message": "..."}.

        Raises ValueError with codes: "send_failed"
        """
        if user.email_verified:
            return {"message": "Email already verified"}

        app_name = await self._get_site_name()
        sent = await self._send_verification_email(user, app_name=app_name)
        if not sent:
            raise ValueError("send_failed")

        return {"message": "Verification email sent"}

    # ── Password Reset ───────────────────────────────────────────────────

    async def request_password_reset(self, email: str) -> dict[str, str]:
        """
        Send a password reset email if the user exists and is eligible.
        Always returns a generic message (anti-enumeration).

        Raises ValueError with codes: "local_auth_disabled"
        """
        if not settings.oidc.local_auth_enabled:
            logger.warning("Password reset refused: local auth disabled (email=%s)", email)
            raise ValueError("local_auth_disabled")

        email = email.strip().lower()
        stmt = select(User).where(func.lower(User.email) == email)
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()

        if user and user.hashed_password and user.is_active:
            app_name = await self._get_site_name()
            await self._send_password_reset_email(user, app_name=app_name)
            logger.info("Password reset email sent for user=%s", user.guid)
        else:
            logger.info("Password reset requested for unknown/ineligible email: %s", email)

        return {"message": "If an account with that email exists, a reset link has been sent."}

    async def reset_password(self, token: str, new_password: str) -> dict[str, str]:
        """
        Reset a user's password using a valid reset token.
        Returns {"message": "..."}.

        Raises ValueError with codes:
            "local_auth_disabled", "invalid_or_expired_token",
            "invalid_token_payload", "user_not_found",
            "email_mismatch", "weak_password"
        """
        if not settings.oidc.local_auth_enabled:
            raise ValueError("local_auth_disabled")

        payload = jwt_handler.verify_password_reset_token(token)
        if not payload:
            logger.warning("Password reset attempted with invalid/expired token")
            raise ValueError("invalid_or_expired_token")

        user_id = payload.get("sub")
        token_email = payload.get("email")
        if not user_id or not token_email:
            logger.warning("Password reset token has incomplete payload")
            raise ValueError("invalid_token_payload")

        stmt = select(User).where(User.guid == uuid_mod.UUID(user_id))
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            logger.warning("Password reset token referenced unknown user=%s", user_id)
            raise ValueError("user_not_found")

        if user.email.lower() != token_email.lower():
            logger.warning(
                "Password reset rejected: token email mismatch user=%s", user.guid,
            )
            raise ValueError("email_mismatch")

        # Single-use enforcement: the token carries a fingerprint of the
        # password hash it was issued against. If the password has since
        # changed (including by a prior successful use of this same link) the
        # fingerprint no longer matches and the token is rejected.
        token_pwf = payload.get("pwf")
        if token_pwf is not None and token_pwf != jwt_handler.password_fingerprint(
            user.hashed_password
        ):
            logger.warning(
                "Password reset rejected: token already used or stale user=%s",
                user.guid,
            )
            raise ValueError("invalid_or_expired_token")

        from pyrate.auth.password import validate_password_strength
        validate_password_strength(new_password)

        user.hashed_password = jwt_handler.get_password_hash(new_password)
        await self.db.commit()

        # Invalidate outstanding refresh tokens so a session opened with the old
        # credentials (or a leaked refresh token) can't survive the reset.
        from pyrate.auth.token_revocation import revoke_user_refresh_tokens

        await revoke_user_refresh_tokens(user.guid)

        logger.info("Password reset completed for user %s (%s)", user.guid, user.email)
        return {"message": "Password has been reset successfully"}

    # ── OIDC User Management ─────────────────────────────────────────────

    async def _update_user_from_oidc(self, user: User, user_data: dict[str, Any]) -> User:
        """Apply OIDC claim fields to an existing user, update last_login, and commit."""
        for field, value in user_data.items():
            if hasattr(user, field) and value is not None:
                if field == "email" and isinstance(value, str):
                    value = value.strip().lower()
                setattr(user, field, value)
        user.last_login = datetime.now(UTC)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    def _create_oidc_user_model(self, user_data: dict[str, Any]) -> User:
        """Build a new User model from OIDC claims (does not persist)."""
        email = user_data["email"].strip().lower()
        fallback_name = user_data.get("preferred_username") or email.split("@")[0]
        return User(
            email=email,
            first_name=user_data.get("first_name") or fallback_name,
            last_name=user_data.get("last_name") or "",
            oidc_sub=user_data["oidc_sub"],
            oidc_provider=user_data.get("oidc_provider", "unknown"),
            preferred_username=user_data.get("preferred_username"),
            picture=user_data.get("picture"),
            locale=user_data.get("locale"),
            groups=user_data.get("groups"),
            is_active=settings.oidc.default_user_active,
            is_superuser=settings.oidc.default_user_superuser,
            email_verified=True,
            last_login=datetime.now(UTC),
        )

    async def get_or_create_oidc_user(self, user_data: dict[str, Any]) -> User:
        """
        Find an existing user by OIDC sub or email, or create a new one.

        Raises ValueError with codes:
            "missing_oidc_sub", "registration_disabled", "email_required"
        """
        oidc_sub = user_data.get("oidc_sub")
        if not oidc_sub:
            raise ValueError("missing_oidc_sub")

        # Search by OIDC subject
        stmt = select(User).where(User.oidc_sub == oidc_sub)
        result = await self.db.execute(stmt)
        user = result.scalar_one_or_none()
        if user:
            return await self._update_user_from_oidc(user, user_data)

        # Search by email
        email = user_data.get("email")
        if isinstance(email, str):
            email = email.strip().lower()
            user_data["email"] = email
        if email:
            stmt = select(User).where(func.lower(User.email) == email)
            result = await self.db.execute(stmt)
            existing_user = result.scalar_one_or_none()
            if existing_user:
                # Auto-linking an OIDC identity into a pre-existing account that
                # has a local password is an account-takeover vector: an
                # attacker who registers the victim's email at a provider that
                # doesn't assert email_verified could otherwise seize the local
                # account. Require an explicit verified-email claim before
                # linking to a password-bearing account. Absence of the claim is
                # treated as unverified.
                email_verified = user_data.get("email_verified") is True
                if existing_user.hashed_password and not email_verified:
                    logger.warning(
                        "Refused OIDC auto-link to local account (email not "
                        "verified by provider) email=%s",
                        email,
                    )
                    raise ValueError("oidc_email_unverified")
                return await self._update_user_from_oidc(existing_user, user_data)

        # Create new user
        if not settings.oidc.auto_register_users:
            raise ValueError("registration_disabled")
        if not email:
            raise ValueError("email_required")

        new_user = self._create_oidc_user_model(user_data)
        self.db.add(new_user)
        await self.db.commit()
        await self.db.refresh(new_user)
        return new_user
