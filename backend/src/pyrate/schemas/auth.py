from datetime import datetime

from pydantic import BaseModel


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserInfo(BaseModel):
    guid: str
    email: str
    first_name: str
    last_name: str
    preferred_username: str | None = None
    picture: str | None = None
    is_active: bool
    is_superuser: bool
    email_verified: bool = False
    last_login: datetime | None = None
    # Language settings
    ui_language: str | None = None
    audio_languages: list[str] | None = None
    subtitle_language: str | None = None
    # Permission hints for frontend
    allowed_libraries: list[str] | None = None


class AuthStatus(BaseModel):
    authenticated: bool
    user: UserInfo | None = None
    oidc_enabled: bool
    local_auth_enabled: bool
    open_registration: bool = False
    auth_methods: list[str]


class BackgroundImageResponse(BaseModel):
    url: str | None
    title: str | None
    year: int | None


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    password: str
