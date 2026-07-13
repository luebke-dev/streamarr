import asyncio
import logging
import os
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response

from streamarr.api.router import router as api_router
from streamarr.api.v1.health import router as health_router
from streamarr.config import connection_settings, load_settings_from_database, settings
from streamarr.services.elasticsearch import elasticsearch_service
from streamarr.services.metrics_sampler import metrics_sampler_loop
from streamarr.utils.logging import request_id_var, setup_logging

# Configure logging before anything else
setup_logging(
    level=connection_settings.log_level,
    fmt=connection_settings.log_format,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Lifecycle manager for FastAPI app - handles startup and shutdown."""
    metrics_stop_event = asyncio.Event()
    metrics_task: asyncio.Task | None = None
    # Startup: Load settings from database
    try:
        await load_settings_from_database()
    except Exception:
        logger.error("Failed to load settings from database", exc_info=True)

    # Load library plugins (static registry, no async needed)
    try:
        from streamarr.libraries import get_registered_plugins

        lib_plugins = get_registered_plugins()
        logger.info("Library plugins loaded: %s", list(lib_plugins.keys()))
    except Exception:
        logger.error("Failed to load library plugins", exc_info=True)

    # Log detected computing provider
    try:
        from streamarr.utils.environment import get_computing_provider_domain

        computing_provider = get_computing_provider_domain()
        logger.info("Detected computing provider: %s", computing_provider)
    except Exception:
        logger.error("Failed to detect computing provider", exc_info=True)

    # Initialize Elasticsearch connection
    await elasticsearch_service.initialize()
    # The sampler loop performs the first sample itself (gated by the leader
    # lock), so no separate warm-up call is needed here — that would sample
    # redundantly on every replica.
    metrics_task = asyncio.create_task(
        metrics_sampler_loop(metrics_stop_event),
        name="streamarr-metrics-sampler",
    )
    try:
        yield
    finally:
        metrics_stop_event.set()
        if metrics_task:
            metrics_task.cancel()
            try:
                await metrics_task
            except asyncio.CancelledError:
                pass
        # Drain active WebSocket connections so clients receive a clean close
        # frame (going away) instead of a dropped TCP connection during a
        # rollout. The manager has no bulk-close method, so iterate a snapshot
        # of its connections and tear each one down individually.
        try:
            from streamarr.services.websocket import get_websocket_manager

            manager = get_websocket_manager()
            for connection in list(manager._connections.values()):
                try:
                    await connection.websocket.close(code=1001)
                except Exception:
                    pass
                try:
                    await manager.disconnect(connection)
                except Exception:
                    pass
        except Exception:
            logger.warning("Failed to drain WebSocket connections", exc_info=True)

        # Shutdown: stop the Redis pub/sub event service (subscriber task +
        # client). Defined but previously never invoked, leaking the connection
        # on shutdown.
        try:
            from streamarr.services.redis_event import shutdown_redis_event_service

            await shutdown_redis_event_service()
        except Exception:
            logger.warning("Failed to shut down Redis event service", exc_info=True)

        # Shutdown: Close Elasticsearch connection
        await elasticsearch_service.close()


app = FastAPI(
    title="Streamarr",
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

def _compute_cors_origins() -> list[str]:
    """Build the allowed-origin list from *live* settings + additive runtime origins.

    ``settings.cors_allowed_origins`` is read fresh here (not captured once at
    import) so the DB-managed ``system.cors_allowed_origins`` override applied
    during lifespan startup actually takes effect — see DynamicCORSMiddleware.
    """
    cors_origins = list(settings.cors_allowed_origins)
    if connection_settings.enable_hosted_app:
        cors_origins.append("https://app.streamarr.media")
    # Capacitor (Android/iOS) apps run from these origins
    cors_origins.append("capacitor://localhost")
    cors_origins.append("https://localhost")
    # Tauri desktop apps use a local custom-protocol origin in production. Keep
    # these runtime origins additive so DB-managed CORS settings cannot lock out
    # the packaged desktop app.
    cors_origins.extend(
        [
            "tauri://localhost",
            "http://tauri.localhost",
            "https://tauri.localhost",
        ]
    )
    return list(dict.fromkeys(cors_origins))


class DynamicCORSMiddleware(CORSMiddleware):
    """CORSMiddleware that re-reads DB-configured origins on each HTTP request.

    Starlette freezes ``allow_origins`` at construction, but the DB override
    (``system.cors_allowed_origins``) is only loaded during lifespan startup —
    after this middleware is built. Recompute the allow list from live settings
    per request so admin-configured origins are actually honored. The set is
    deterministic (it only changes at startup), so the per-request refresh is
    cheap and race-free.
    """

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            self.allow_origins = _compute_cors_origins()
        await super().__call__(scope, receive, send)


app.add_middleware(
    DynamicCORSMiddleware,
    allow_origins=_compute_cors_origins(),
    allow_credentials=True,
    # Narrowed to the methods / headers the app actually uses. If a future
    # feature needs a new method or header, extend these lists explicitly.
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Accept",
        "Accept-Language",
        "X-Requested-With",
        "X-Device-Id",
        "If-Modified-Since",
        "If-None-Match",
        "Range",
        "X-Request-ID",
    ],
    expose_headers=["Content-Range", "Content-Disposition", "ETag", "X-Request-ID"],
)

allowed_hosts = [
    h.strip() for h in os.environ.get("ALLOWED_HOSTS", "").split(",") if h.strip()
]
if not allowed_hosts:
    # No configured hosts: fall back to accepting any Host header, but do NOT
    # do it silently — an open TrustedHost default enables Host-header/absolute-
    # URL confusion. Warn loudly so the operator sets ALLOWED_HOSTS in prod.
    logger.warning(
        "ALLOWED_HOSTS is not set — TrustedHostMiddleware accepts ALL Host "
        "headers ('*'). Set ALLOWED_HOSTS to your public hostname(s) in production."
    )
    allowed_hosts = ["*"]
app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

metrics_token = os.environ.get("METRICS_TOKEN", "")


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    """Gate /metrics behind a required token and add baseline security headers."""
    if request.url.path == "/metrics":
        # Fail closed: /metrics is only served when METRICS_TOKEN is configured.
        # Without it the endpoint must NOT be open (it leaks route cardinality,
        # user/session counts, latency histograms). 404 so its existence isn't
        # revealed; when a token IS set, require the matching bearer.
        if not metrics_token:
            return Response(status_code=404)
        expected = f"Bearer {metrics_token}"
        if not secrets.compare_digest(request.headers.get("authorization", ""), expected):
            return Response(status_code=403)
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    if proto == "https":
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=63072000; includeSubDomains"
        )
    return response


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    """Attach request_id to logs and responses, and emit one structured access line."""
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    token = request_id_var.set(request_id)
    started = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        if request.url.path != "/metrics":
            logger.info(
                "HTTP request completed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                    "client_ip": request.client.host if request.client else None,
                },
            )
        request_id_var.reset(token)


# Prometheus instrumentation — default HTTP metrics (count, latency, in-progress,
# bytes) plus /metrics endpoint. Scraping is gated by the proxy; expose the
# endpoint only on the internal docker network in production.
try:
    from prometheus_fastapi_instrumentator import Instrumentator

    Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
except Exception as _prom_exc:  # pragma: no cover - optional dep fallback
    logging.getLogger(__name__).warning(
        "prometheus-fastapi-instrumentator unavailable: %s", _prom_exc,
    )

# Get the backend directory path
backend_dir = Path(__file__).parent.parent.parent
static_dir = backend_dir / "static"

# Ensure static directory exists
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
# Liveness/readiness probes at the app root, without the /api prefix and
# without authentication so orchestrators can reach them directly.
app.include_router(health_router)
app.include_router(api_router, prefix="/api")
