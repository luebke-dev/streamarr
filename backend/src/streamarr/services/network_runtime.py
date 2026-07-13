"""Runtime helpers for applying network settings."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.services.system_settings import SystemSettingsService


@dataclass
class NetworkRuntimeConfig:
    bind_host: str
    bind_port: int
    enable_https: bool
    ssl_certificate_path: str | None
    ssl_key_path: str | None
    remote_access_enabled: bool
    public_hostname: str | None
    source: str = "database"
    ssl_files_present: bool = False

    @property
    def restart_required(self) -> bool:
        return (
            os.environ.get("STREAMARR_EFFECTIVE_BIND_HOST") not in (None, self.bind_host)
            or os.environ.get("STREAMARR_EFFECTIVE_BIND_PORT") not in (
                None,
                str(self.bind_port),
            )
            or os.environ.get("STREAMARR_EFFECTIVE_ENABLE_HTTPS") not in (
                None,
                str(self.enable_https).lower(),
            )
        )

    @property
    def scheme(self) -> str:
        return "https" if self.enable_https else "http"

    @property
    def public_base_url(self) -> str | None:
        if not self.public_hostname:
            return None
        default_port = 443 if self.enable_https else 80
        port_suffix = "" if self.bind_port == default_port else f":{self.bind_port}"
        return f"{self.scheme}://{self.public_hostname}{port_suffix}"

    @property
    def internal_base_url(self) -> str:
        host = "127.0.0.1" if self.bind_host in {"0.0.0.0", "::"} else self.bind_host
        return f"{self.scheme}://{host}:{self.bind_port}"

    @property
    def reverse_proxy_env(self) -> dict[str, str]:
        return {
            "STREAMARR_UPSTREAM_HOST": self.bind_host,
            "STREAMARR_UPSTREAM_PORT": str(self.bind_port),
            "STREAMARR_UPSTREAM_SCHEME": self.scheme,
            "STREAMARR_PUBLIC_BASE_URL": self.public_base_url or "",
            "STREAMARR_INTERNAL_BASE_URL": self.internal_base_url,
        }


async def get_network_runtime_config(db: AsyncSession) -> NetworkRuntimeConfig:
    """Load network settings in the shape needed by the process runner."""
    try:
        settings = await SystemSettingsService(db).get_network_settings()
        source = "database"
    except Exception:
        settings = {}
        source = "defaults"

    cert_path = settings.get("ssl_certificate_path")
    key_path = settings.get("ssl_key_path")
    enable_https = bool(settings.get("enable_https", False))
    ssl_files_present = bool(
        enable_https
        and cert_path
        and key_path
        and Path(cert_path).is_file()
        and Path(key_path).is_file()
    )

    return NetworkRuntimeConfig(
        bind_host=str(settings.get("bind_host") or "0.0.0.0"),
        bind_port=int(settings.get("bind_port") or 8000),
        enable_https=enable_https,
        ssl_certificate_path=cert_path,
        ssl_key_path=key_path,
        remote_access_enabled=bool(settings.get("remote_access_enabled", True)),
        public_hostname=settings.get("public_hostname"),
        source=source,
        ssl_files_present=ssl_files_present,
    )
