# Lightrays

WebRTC desktop streaming server written in Rust. Streams a virtual Wayland compositor to browsers using GStreamer and WebRTC, with hardware-accelerated encoding (VA-API). Application containers (XFCE, Firefox, Steam, etc.) are managed via the Docker API using [Games on Whales](https://games-on-whales.github.io/) images.

## Features

- **WebRTC streaming** with H.264/H.265 hardware encoding (VA-API)
- **Virtual Wayland compositor** (Smithay-based `gst-wayland-display`)
- **Docker container management** via bollard (no Docker CLI needed)
- **Keyboard, mouse & pointer lock** input forwarding over WebRTC data channels
- **PulseAudio** per-session audio sinks
- **Ultra-wide support** — automatic H.265 fallback for resolutions wider than 4096px

## Quick Start

Lightrays ships two compose overrides:

```bash
# Local development — auth disabled, verbose logging, source bind-mount.
cd docker
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build

# Hardened production — fails fast unless LIGHTRAYS_JWT_SECRET and
# LIGHTRAYS_CORS_ORIGINS are provided by the environment.
LIGHTRAYS_JWT_SECRET=$(openssl rand -hex 32) \
LIGHTRAYS_CORS_ORIGINS=https://pyrate.example.com \
  docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

The privileged bits required for desktop streaming (host networking,
Docker socket, `/dev/dri`, `/dev/input`, `SYS_ADMIN`/`NET_ADMIN`) live in
the base file and apply to both modes — they're intrinsic to running
container-backed streams. The overrides only change what's safe to differ
between dev and prod.

Open `http://localhost:8080` in your browser (dev mode).

## Configuration

All configuration is via environment variables:

| Variable | Default | Description |
|---|---|---|
| `LIGHTRAYS_HOSTNAME` | `Lightrays` | Server hostname |
| `LIGHTRAYS_API_BIND_ADDR` | `0.0.0.0` | Management API bind address |
| `LIGHTRAYS_API_PORT` | `8080` | API listen port |
| `LIGHTRAYS_STREAMING_BIND_ADDR` | `0.0.0.0` | WebSocket streaming bind address |
| `LIGHTRAYS_STREAMING_PORT` | `8081` | Dedicated WebSocket listen port |
| `LIGHTRAYS_METRICS_BIND_ADDR` | `127.0.0.1` | Metrics bind address (localhost-only by default) |
| `LIGHTRAYS_METRICS_PORT` | `9090` | Prometheus metrics listen port |
| `LIGHTRAYS_STUN_SERVER` | `stun://stun.l.google.com:19302` | STUN server for WebRTC ICE |
| `LIGHTRAYS_TURN_SERVER` | *(empty)* | TURN server URL |
| `LIGHTRAYS_TURN_USERNAME` | *(empty)* | TURN credentials |
| `LIGHTRAYS_TURN_PASSWORD` | *(empty)* | TURN credentials |
| `LIGHTRAYS_CORS_ORIGINS` | `*` | Comma-separated allowed CORS origins |
| `LIGHTRAYS_DOCKER_SOCKET` | `/var/run/docker.sock` | Docker socket path |
| `LIGHTRAYS_STATE_DIR` | `/etc/lightrays` | Persistent state directory |
| `LIGHTRAYS_GOW_IMAGE` | `ghcr.io/games-on-whales/steam:edge` | Image used by the built-in `gow-steam` runtime profile |
| `LIGHTRAYS_JWT_SECRET` | *(empty)* | HS256 secret for JWT verification (required unless explicitly disabled) |
| `LIGHTRAYS_AUTH_DISABLED` | `false` | Must be `true` to start without `LIGHTRAYS_JWT_SECRET` |
| `LIGHTRAYS_SESSION_TIMEOUT_SECS` | `3600` | Idle-based session timeout (0 = disabled) |
| `LIGHTRAYS_RECONNECT_GRACE_SECS` | `30` | Grace period before stopping a disconnected session |
| `LIGHTRAYS_WS_TICKET_TTL_SECS` | `120` | Short-lived WebSocket ticket lifetime |
| `LIGHTRAYS_DUMP_CONTAINER_LOGS` | `false` | Dump container log tails on early exit (verbose; off by default) |
| `RUST_LOG` | `info` | Log level |

## Authentication

When `LIGHTRAYS_JWT_SECRET` is set, every API and WebSocket endpoint requires
a valid HS256 token:

- **HTTP endpoints** (`/api/launch`, `/api/stop`, `/api/stats/:session_id`):
  `Authorization: Bearer <jwt>` is required. The token's `sub` claim binds
  the resulting session to the principal; `/api/stop` and
  `/api/stats/:session_id` are restricted to the owning subject or callers
  holding the `lightrays:admin` scope.
- **WebSocket** (`/api/lightrays-ws/:session_id`): browsers connect with
  `["lightrays", ws_ticket]` as the `Sec-WebSocket-Protocol` value. The
  ticket comes from the launch response, is scoped to `lightrays:ws`,
  bound to the `session_id`, and lives for `LIGHTRAYS_WS_TICKET_TTL_SECS`
  seconds. Query-string `?token=` is rejected.
- **Disabling auth**: set `LIGHTRAYS_AUTH_DISABLED=true` to start without
  a secret. All callers are then treated as anonymous admins; this is
  intended for local development and clearly logged at startup.

## Observability

Prometheus metrics are exposed on `LIGHTRAYS_METRICS_BIND_ADDR:LIGHTRAYS_METRICS_PORT`
(localhost-only by default).

| Metric | Type | Notes |
|---|---|---|
| `lightrays_sessions_active` | gauge | Currently active sessions |
| `lightrays_sessions_launched_total` | counter | Sessions launched |
| `lightrays_sessions_stopped_total` | counter | Sessions stopped |
| `lightrays_sessions_idle_timeout_total` | counter | Sessions reaped by idle timeout |
| `lightrays_launch_stage_duration_seconds{stage}` | histogram | Duration per launch stage: `compositor`, `pulse`, `container` |
| `lightrays_launch_errors_total{stage}` | counter | Launch failures by stage |
| `lightrays_containers_started_total` | counter | Container starts |
| `lightrays_container_deaths_total{exit_code}` | counter | Container exits by code |
| `lightrays_container_last_exit_code{runtime_profile}` | gauge | Last container exit code, per profile |
| `lightrays_webrtc_connections_active` | gauge | Active WebRTC connections |
| `lightrays_webrtc_connections_total` | counter | WebRTC connections established |
| `lightrays_webrtc_failures_total` | counter | WebRTC failures |
| `lightrays_ws_reconnects_total` | counter | WebSocket reconnects within the grace window |

## API

### `POST /api/launch`

Start a streaming session. Mount, device, capability, and container-name policy
are resolved server-side from `runtime_profile`. `gow-steam` uses
`LIGHTRAYS_GOW_IMAGE` by default and may receive a single validated
`docker_image` override from a trusted backend.

```json
{
  "title": "Steam",
  "width": 1920,
  "height": 1080,
  "fps": 60,
  "bitrate_kbps": 10000,
  "runtime_profile": "gow-steam",
  "docker_image": "ghcr.io/games-on-whales/steam:edge",
  "app_id": "user-guid-game-guid",
  "keyboard_layout": "de",
  "start_virtual_compositor": true,
  "start_audio_server": true,
  "render_node": "/dev/dri/renderD128"
}
```

Response:

```json
{
  "session_id": "a1b2c3d4",
  "ws_url": "/api/lightrays-ws/a1b2c3d4",
  "ws_ticket": "short-lived-jwt",
  "streaming_port": 8081,
  "ice_servers": []
}
```

### `POST /api/stop`

Stop a session and its container.

```json
{
  "session_id": "a1b2c3d4"
}
```

### `WebSocket /api/lightrays-ws/:session_id`

After launching, connect a WebSocket to the returned `ws_url` for WebRTC
signaling. Browser clients authenticate by passing `["lightrays", ws_ticket]`
as WebSocket subprotocols; query-string bearer tokens are not accepted.

**Server → Client:**

| Message | Description |
|---|---|
| `{"type": "offer", "sdp": "..."}` | WebRTC SDP offer |
| `{"type": "ice", "candidate": "...", "sdpMLineIndex": 0}` | ICE candidate |

**Client → Server:**

| Message | Description |
|---|---|
| `{"type": "answer", "sdp": "..."}` | WebRTC SDP answer |
| `{"type": "ice", "candidate": "...", "sdpMLineIndex": 0}` | ICE candidate |
| `{"type": "key", "code": "KeyA", "pressed": true}` | Keyboard input |
| `{"type": "mousemove", "dx": 5, "dy": -3}` | Relative mouse (pointer lock) |
| `{"type": "mouseabs", "x": 100, "y": 200, "w": 1920, "h": 1080}` | Absolute mouse |
| `{"type": "mousebutton", "button": 0, "pressed": true}` | Mouse button |
| `{"type": "wheel", "dx": 0, "dy": -120}` | Scroll wheel |

Input messages can also be sent over the WebRTC data channel (label: `input`) for lower latency.

### Session Flow

1. `POST /api/launch` → get `session_id` and `ws_url`
2. Open WebSocket to `ws_url`
3. Receive `offer` → create `RTCPeerConnection` → set remote description → create answer → send `answer`
4. Exchange `ice` candidates
5. Receive video/audio tracks via WebRTC
6. Send input via WebSocket or data channel
7. `POST /api/stop` or close WebSocket to end

## Architecture

```
Browser  <──WebRTC──>  lightrays (Rust)
                          ├── axum HTTP/WS server
                          ├── GStreamer WebRTC pipeline
                          ├── Smithay Wayland compositor
                          └── bollard Docker API
                                └── GOW app containers
```

## Requirements

- Docker with compose
- GPU with VA-API support (AMD/Intel) for hardware encoding
- Host networking (for WebRTC ICE)

## License

MIT
