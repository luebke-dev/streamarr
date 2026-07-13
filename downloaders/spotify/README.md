# spotify-downloader

HTTP API for downloading Spotify tracks as OGG files using [librespot](https://github.com/librespot-org/librespot).

Files are saved using the Spotify track ID as the filename (e.g. `3n3Ppam7vgaVa1iaRUc9Lp.ogg`).

## Features

- **REST API** — Download tracks via POST request
- **Job Queue** — Priority-based async processing with status tracking
- **SQLite** — Persistent job history (WAL mode) with crash recovery
- **Webhooks** — Configurable notifications with retries and exponential backoff
- **OAuth Login** — Spotify authentication via librespot-oauth (PKCE)
- **Credential Caching** — Log in once, token is cached
- **Web UI** — Optional browser interface for managing downloads
- **Docker** — Multi-stage build, minimal Debian image

## Requirements

- Spotify Premium account
- Docker (recommended) or Rust 1.94+

## Quickstart (Docker)

```bash
docker run -d \
  --name spotify-downloader \
  --network host \
  -v spotify-data:/data \
  registry.gitlab.com/streamarr.media/spotify-downloader:latest
```

On first start, the Spotify OAuth URL is printed to the logs:

```bash
docker logs -f spotify-downloader
```

Open the displayed URL in your browser and log in. Authentication completes automatically via the callback on port 8898. The container uses host networking so the OAuth listener is directly reachable. For headless systems, forward port 8898 via SSH:

```bash
ssh -L 8898:localhost:8898 server
```

## API

### Create a download job

```bash
curl -X POST http://localhost:3000/api/jobs \
  -H 'Content-Type: application/json' \
  -d '{"track_id": "3n3Ppam7vgaVa1iaRUc9Lp"}'
```

The `track_id` field accepts any of these formats:
- Track ID: `3n3Ppam7vgaVa1iaRUc9Lp`
- Spotify URI: `spotify:track:3n3Ppam7vgaVa1iaRUc9Lp`
- Spotify URL: `https://open.spotify.com/track/3n3Ppam7vgaVa1iaRUc9Lp`

Response (`202 Accepted`):
```json
{
  "id": "f7e3a7a4-a814-4e3c-b9fb-845d02264bb4",
  "track_id": "3n3Ppam7vgaVa1iaRUc9Lp",
  "status": "queued",
  "priority": 5,
  "progress": 0,
  "created_at": "2026-03-14T23:45:25Z"
}
```

If the track was already downloaded, the response is `200 OK` with status `completed` (cache hit).

### List jobs

```bash
curl http://localhost:3000/api/jobs
```

### Get job status

```bash
curl http://localhost:3000/api/jobs/{id}
```

### Delete a job

```bash
curl -X DELETE http://localhost:3000/api/jobs/{id}
```

Response: `204 No Content`

### Download a file

```bash
curl -O http://localhost:3000/api/files/3n3Ppam7vgaVa1iaRUc9Lp
```

Returns the OGG file with `Content-Disposition: attachment`.

### Health check

```bash
curl http://localhost:3000/api/health
```

### Web UI

When `ENABLE_WEBUI` is set, a web interface is available at `http://localhost:3000/` for submitting downloads, viewing job status, and downloading files.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SERVER_HOST` | `0.0.0.0` | HTTP server bind address |
| `SERVER_PORT` | `3000` | HTTP server port |
| `DATABASE_PATH` | `/data/spotify.db` | SQLite database path |
| `CONFIG_DIR` | `/data/config` | Directory for Spotify credentials cache |
| `DOWNLOAD_DIR` | `/data/downloads` | Directory for downloaded files |
| `BITRATE` | `320` | Audio bitrate: `96`, `160`, or `320` |
| `ENABLE_WEBUI` | _(unset)_ | Set to any value to enable the web UI at `/` |
| `WEBHOOK_URL` | _(empty)_ | URL to POST webhook notifications to |
| `WEBHOOK_TIMEOUT_SECS` | `10` | Webhook HTTP timeout |
| `WEBHOOK_MAX_RETRIES` | `3` | Webhook retry count with exponential backoff |
| `RUST_LOG` | `spotify_downloader=info,librespot=warn` | Log level |

## Build locally

```bash
cargo build --release
./target/release/spotify-downloader
```
