# usenet-downloader

HTTP API for downloading files from Usenet newsgroups via NZB files using NNTP with multi-connection support, progress tracking, and priority queuing.

## Features

- **REST API** — Create, monitor, and cancel Usenet downloads
- **Job Queue** — Priority-based async processing with configurable concurrency
- **SQLite** — Persistent job history (WAL mode) with crash recovery
- **Webhooks** — Configurable notifications with retries and exponential backoff
- **Multi-Connection** — Parallel NNTP connections for maximum throughput
- **TLS** — Encrypted connections to Usenet providers
- **yEnc Decoding** — Built-in binary content decoding
- **Docker** — Multi-stage build, minimal Alpine image

## Requirements

- Usenet provider account (host, username, password)
- Docker (recommended) or Rust 1.87+

## Quickstart (Docker)

```bash
docker run -d \
  --name usenet-downloader \
  -p 3000:3000 \
  -v usenet-data:/data \
  -v usenet-downloads:/downloads \
  -e USENET_HOST=news.example.com \
  -e USENET_USERNAME=user \
  -e USENET_PASSWORD=pass \
  registry.gitlab.com/streamarr.media/usenet-downloader:latest
```

## API

### Create a download job

```bash
curl -X POST http://localhost:3000/api/jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "My Download",
    "nzb_url": "https://example.com/file.nzb"
  }'
```

NZB source (one required):
- `nzb_url` — URL to an NZB file (fetched by the server)
- `nzb_content` — Base64-encoded NZB XML content

Optional fields:
- `priority` — 1-10, default 5 (higher = processed first)
- `category` — Category tag (e.g. `tv`, `movies`)
- `destination` — Override download directory
- `webhook_url` — Per-job webhook URL override

Response (`201 Created`):
```json
{
  "id": "a1b2c3d4-...",
  "name": "My Download",
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
| `completed` | Successfully downloaded |
| `failed` | Download failed |
| `cancelled` | Manually cancelled |

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SERVER_HOST` | `0.0.0.0` | HTTP server bind address |
| `SERVER_PORT` | `3000` | HTTP server port |
| `DATABASE_PATH` | `/data/usenet.db` | SQLite database path |
| `DOWNLOAD_DIR` | `/downloads` | Directory for downloaded files |
| `DOWNLOAD_TEMP_DIR` | `/downloads/.tmp` | Temp directory for in-progress downloads |
| `DOWNLOAD_MAX_CONCURRENT_JOBS` | `3` | Maximum parallel downloads |
| `USENET_HOST` | _(required)_ | Usenet server hostname |
| `USENET_PORT` | `563` | Usenet server port |
| `USENET_TLS` | `true` | Enable TLS encryption |
| `USENET_USERNAME` | _(required)_ | Usenet account username |
| `USENET_PASSWORD` | _(required)_ | Usenet account password |
| `USENET_CONNECTIONS` | `8` | Number of parallel NNTP connections |
| `WEBHOOK_URL` | _(empty)_ | Default webhook URL for notifications |
| `WEBHOOK_TIMEOUT_SECS` | `10` | Webhook HTTP timeout |
| `WEBHOOK_MAX_RETRIES` | `3` | Webhook retry count with exponential backoff |
| `RUST_LOG` | `usenet_downloader=info,tower_http=info` | Log level |

## Build locally

```bash
cargo build --release
./target/release/usenet-downloader
```
