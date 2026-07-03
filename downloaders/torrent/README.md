# torrent-downloader

HTTP API for downloading files from torrent magnet links and .torrent files with DHT support, priority queuing, and progress tracking.

## Features

- **REST API** — Create, monitor, and cancel torrent downloads
- **Job Queue** — Priority-based async processing with configurable concurrency
- **SQLite** — Persistent job history (WAL mode) with crash recovery
- **Webhooks** — Configurable notifications with retries and exponential backoff
- **DHT** — Distributed hash table for peer discovery
- **Seeding** — Configurable seed ratio before completion
- **Docker** — Multi-stage build, minimal Alpine image

## Requirements

- Docker (recommended) or Rust 1.88+

## Quickstart (Docker)

```bash
docker run -d \
  --name torrent-downloader \
  -p 3000:3000 \
  -p 6881:6881 \
  -p 6881:6881/udp \
  -v torrent-data:/data \
  -v torrent-downloads:/downloads \
  registry.gitlab.com/pyrate.media/torrent-downloader:latest
```

## API

### Create a download job

```bash
curl -X POST http://localhost:3000/api/jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "My Torrent",
    "magnet_uri": "magnet:?xt=urn:btih:..."
  }'
```

Torrent source (one required):
- `magnet_uri` — Magnet link
- `torrent_url` — URL to a .torrent file (fetched by the server)
- `torrent_content` — Base64-encoded .torrent file bytes

Optional fields:
- `name` — Display name (auto-detected from magnet/torrent if omitted)
- `priority` — 1-10, default 5 (higher = processed first)
- `category` — Category tag (e.g. `movies`, `tv`)
- `destination` — Override download directory
- `webhook_url` — Per-job webhook URL override

Response (`201 Created`):
```json
{
  "id": "a1b2c3d4-...",
  "name": "My Torrent",
  "status": "queued",
  "priority": 5,
  "progress": 0,
  "created_at": "2026-03-14T23:45:25Z"
}
```

### List jobs

```bash
curl http://localhost:3000/api/jobs
```

### Get job status

```bash
curl http://localhost:3000/api/jobs/{id}
```

### Cancel a job

```bash
curl -X DELETE http://localhost:3000/api/jobs/{id}
```

### Health check

```bash
curl http://localhost:3000/api/health
```

### Job States

| Status | Description |
|---|---|
| `queued` | Waiting to start |
| `downloading` | Actively downloading |
| `seeding` | Download complete, seeding to target ratio |
| `completed` | Finished |
| `failed` | Download failed |
| `cancelled` | Manually cancelled |

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SERVER_HOST` | `0.0.0.0` | HTTP server bind address |
| `SERVER_PORT` | `3000` | HTTP server port |
| `DATABASE_PATH` | `/data/torrent-downloader.db` | SQLite database path |
| `DOWNLOAD_DIR` | `/downloads` | Directory for downloaded files |
| `MAX_CONCURRENT_DOWNLOADS` | `5` | Maximum parallel downloads |
| `ENABLE_DHT` | `true` | Enable DHT for peer discovery |
| `LISTEN_PORT` | `6881` | Port for incoming torrent connections |
| `SEED_RATIO` | `0.0` | Seed ratio before marking complete (0 = no seeding) |
| `WEBHOOK_URL` | _(empty)_ | Default webhook URL for notifications |
| `WEBHOOK_TIMEOUT_SECS` | `10` | Webhook HTTP timeout |
| `WEBHOOK_MAX_RETRIES` | `3` | Webhook retry count with exponential backoff |
| `RUST_LOG` | `torrent_downloader=info,tower_http=info` | Log level |

## Build locally

```bash
cargo build --release
./target/release/torrent-downloader
```
