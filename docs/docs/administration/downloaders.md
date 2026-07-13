# Download Clients

Download clients fetch the releases found by your [indexers](indexers.md). streamarr.media speaks to two well-known external clients — **SABnzbd** (Usenet) and **Deluge** (BitTorrent) — and ships **three built-in Rust downloader services** for torrents, Usenet, and Spotify music.

## Supported client types

| Type | Protocol | What it is |
|------|----------|------------|
| **SABnzbd** | Usenet | External SABnzbd instance, authenticated with its API key |
| **Deluge** | BitTorrent | External Deluge instance, via its Web UI password |
| **Torrent service** (`torrent_downloader`) | BitTorrent | Built-in service using the librqbit engine |
| **Usenet service** (`usenet_downloader`) | Usenet | Built-in NNTP service with multi-server failover |
| **SpotDL** (`spotdl`) | Spotify | Built-in Spotify music service using librespot |

When a download starts, the client is chosen by **link type**, not media type: NZB links go to the Usenet service or SABnzbd, magnet/torrent links to the torrent service or Deluge, and Spotify links always to SpotDL. Music downloads therefore require a SpotDL downloader to be configured.

!!! note "SpotDL is a legacy name"
    The Spotify service is registered under the historical name *SpotDL*, but it does not use the spotdl tool — it downloads native OGG Vorbis audio through librespot.

## Managing downloaders

Navigate to **Admin → Downloaders** to see all configured download clients, with their **Label**, **Host**, **Type**, **SSL**/**Verify SSL** flags, and creation date. Each row can be edited or deleted.

Click **Add Downloader**, give the client a descriptive **Label**, and pick the **Downloader Type**. Each downloader record stores a host URL and, where needed, a credential:

| Type | Host | Credential |
|------|------|-----------|
| SABnzbd | Base URL of the instance, e.g. `http://sabnzbd:8080` | SABnzbd API key (Config → General in SABnzbd) |
| Deluge | Base URL of the Deluge Web UI, e.g. `http://deluge:8112` | Web UI password (stored in the API-key field) |
| Built-in services | Base URL of the service, e.g. `http://torrent-downloader:3000` | None |

!!! note "Registering the built-in torrent and Usenet services"
    The **Add Downloader** dialog currently offers SABnzbd, Deluge, and SpotDL. The built-in torrent and Usenet services are registered via the API instead — `POST /api/downloaders` with `type` set to `torrent_downloader` or `usenet_downloader` and `host` pointing at the service.

Saved API keys are never sent back to the browser; when editing, leave the field empty to keep the existing key. A downloader that is temporarily unreachable is retried with backoff and skipped for the current poll rather than failing your downloads outright.

## The built-in downloader services

The three services are part of the standard Docker Compose deployment (see the [deployment overview](../deployment/overview.md)) and are configured entirely through environment variables on their containers:

=== "Torrent"

    Accepts magnet URIs and `.torrent` URLs via librqbit. DHT peer discovery can be toggled (`ENABLE_DHT`), concurrency is capped by `MAX_CONCURRENT_DOWNLOADS` (default 5), and finished downloads keep **seeding** until the configured `SEED_RATIO` is reached (`0` = no seeding).

=== "Usenet"

    A full NNTP client: multi-connection downloads over TLS, yEnc decoding with CRC32 checks, **PAR2 verify and repair** (recovery volumes are only fetched when actually needed), and **Direct Unpack** — archives are extracted with unrar while later volumes are still downloading, including password-protected releases. The primary server is set via `USENET_HOST`, `USENET_PORT`, `USENET_USERNAME`, `USENET_PASSWORD`, and `USENET_CONNECTIONS`; up to five prioritized backup servers (`BACKUP_SERVER_1_HOST`, …) provide **failover**, each with its own connection count and retention window. An optional global speed cap is available via `SPEED_LIMIT_KBPS`.

=== "Spotify"

    Downloads tracks as native OGG Vorbis through librespot — no re-encoding. Requires a **Spotify Premium** account. On first start the service logs an OAuth login URL; open it, sign in, and the callback (port 8898) completes authentication. Credentials are cached afterwards, so this is a one-time step. Audio quality is set with `BITRATE` (`96`, `160`, or `320`, default 320).

### Webhook callbacks

The built-in services report finished or failed jobs back to the backend via webhooks (`/api/webhooks/torrent`, `/api/webhooks/usenet`, `/api/webhooks/spotdl`), authenticated with a shared secret sent in the `X-Webhook-Secret` header. Both sides read it from the same environment variable:

- Backend: `DOWNLOADER_WEBHOOK_SECRET`
- Downloader containers: `WEBHOOK_SECRET` (plus `WEBHOOK_URL`)

!!! warning "The secret is mandatory"
    The webhook endpoints fail closed: if `DOWNLOADER_WEBHOOK_SECRET` is not set on the backend, callbacks are rejected and completed downloads will never be imported. The standard compose files wire this up for you.

When a job fails, the backend automatically tries an alternative link for the same release, and if none is left it blacklists the release and queues the next candidate.

### Volume and path mapping

Downloaders and backend share files through bind-mounted volumes, and a downloader reports paths *as seen inside its own container*. The backend translates them using a mount map, overridable with the `DOWNLOADER_MOUNT_MAP` environment variable (JSON: `{"<name>": ["<remote_prefix>", "<local_prefix>"]}`). The defaults mirror the standard compose mounts:

| Downloader | Path in downloader | Path in backend |
|------------|--------------------|-----------------|
| `torrent` | `/downloads` | `/torrent-downloads` |
| `spotdl` | `/data/downloads` | `/spotdl-downloads` |
| `usenet` | `/downloads` | `/downloads` |

Only override this if you change the volume layout — a wrong mapping makes imports fail even though downloads complete.

## Monitoring the download queue

Navigate to **Admin → Downloads** to watch the live queue. The table shows media type, title (linked to the media item), status, downloader, progress, speed, creation time, and which user started the download, with a free-text search and a status filter (*Pending, Queued, Downloading, Paused, Completed, Failed, Imported*). The status column also surfaces detail phases such as *"Searching for releases"*, *"Trying another release"*, and *"Importing into library"*.

Active downloads can be **paused**, **resumed**, or **deleted** from the actions column. Progress is refreshed by polling the clients every few seconds; completions from the built-in torrent and Spotify services arrive instantly via webhook.

The [admin dashboard](dashboard.md) also shows active download activity at a glance, and download metrics are exported for [monitoring](monitoring.md).
