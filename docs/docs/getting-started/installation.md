# Installation

streamarr.media ships four supported deployment models. All of them run the same stack — API, workers, scheduler, frontend, PostgreSQL 16, Redis 7, and Elasticsearch 9.2.0 — they differ in how you install, configure, and operate it.

| Model | Use when | Source of truth |
|-------|----------|-----------------|
| **One-line installer** | First single-host install, guided setup | `deployment/install.sh` |
| **Docker Compose (prod)** | Single host, full service set, pre-built registry images | `deployment/docker/docker-compose.yml` |
| **Helm / Kubernetes** | Cluster deployments | `deployment/helm/streamarr` (also published as an OCI chart) |
| **Podman quadlets** | Single host with Podman + systemd, lean variant | `deployment/quadlets/*.container` |

!!! note "Local development"
    The `docker-compose.yml` in the repository root builds all images locally and is **for development only** — it is not a production artifact. See the [Development Overview](../developer-guide/overview.md).

## System requirements

- **Host**: Linux with Docker Engine + Compose v2, Podman with quadlet support, or a Kubernetes cluster. The installer supports Debian 12+, Ubuntu 22.04+, Fedora 39+, and RHEL/CentOS/Rocky/Alma 9+.
- **CPU**: 2+ cores; 4+ recommended for transcoding (or a VA-API/NVENC-capable GPU).
- **RAM**: 8 GB recommended — PostgreSQL, Redis, and Elasticsearch run alongside the app.
- **Storage**: as much as your media needs, plus space for the transcode cache.

## One-line installer

The fastest path on a fresh Linux host:

```bash
curl -fsSL https://get.streamarr.media | sudo bash
```

The interactive installer:

1. Installs Docker Engine and Compose for your distribution.
2. Asks for install directory (default `/opt/streamarr`), data directory (default `/var/lib/streamarr`), ports, and optional services (Elasticsearch on by default; SABnzbd and Lightrays opt-in).
3. Generates secrets with `openssl rand` and writes a `chmod 600` `.env`.
4. Writes a Docker Compose file, starts the stack, and installs a `streamarr.service` systemd unit so it starts on boot.

!!! note "Installer output is a subset"
    The installer emits only the services you opt into. It does not include the Rust torrent/spotify/usenet downloader services — if you want the full stack, deploy `deployment/docker/docker-compose.yml` directly.

## Docker Compose (single host)

The maintained production Compose file uses pre-built images from `registry.gitlab.com/streamarr.media`.

```bash
mkdir /srv/streamarr && cd /srv/streamarr
# copy deployment/docker/docker-compose.yml and deployment/docker/.env.example here
cp .env.example .env
docker compose up -d
```

Edit `.env` before the first start. At minimum set:

| Variable | Purpose |
|----------|---------|
| `SECRET_KEY` | JWT signing key — `openssl rand -hex 32` |
| `POSTGRES_PASSWORD` | Database password |
| `LIGHTRAYS_JWT_SECRET` | Shared secret between backend and Lightrays |
| `DOWNLOADER_WEBHOOK_SECRET` | Authenticates downloader webhook callbacks |
| `DATA_DIR` | Absolute host path for media, cache, and downloads |
| `PROJECT_ROOT` | Absolute **host** path of the install dir — required for the FFmpeg transcode containers spawned via the Docker socket |
| `APP_URL` | Canonical public URL, used for links and OIDC callbacks |

!!! warning "Secrets are never committed"
    `.env` is git-ignored by design. Keep it `chmod 600` and back it up with your database.

## Kubernetes (Helm)

The chart is published as an OCI artifact:

```bash
helm install streamarr oci://registry.gitlab.com/streamarr.media/deployment/streamarr \
  --namespace streamarr --create-namespace \
  --set secrets.postgresPassword=$(openssl rand -hex 32) \
  --set secrets.secretKey=$(openssl rand -hex 32) \
  --set secrets.lightraysJwtSecret=$(openssl rand -hex 32) \
  --set secrets.downloaderWebhookSecret=$(openssl rand -hex 32)
```

Alternatively set `secrets.existingSecret` to mount a pre-provisioned Secret. Notable options in `values.yaml`:

- **External PostgreSQL** (e.g. CloudNativePG) via `postgres.enabled: false` + `postgres.external`.
- **Persistence**: `pvc` (default, needs RWX storage) or `hostPath` — required when FFmpeg transcode Job pods must see the same files as the workers.
- **Native transcoding**: the backend auto-detects Kubernetes and spawns FFmpeg/ffprobe/trickplay Jobs; the chart ships the ServiceAccount and RBAC, with node selectors via `transcoding.*`.
- **Ingress + TLS**, GPU for Lightrays, dedicated transcode/gaming node pools.

!!! warning "Helm caveats"
    Lightrays still needs the host Docker socket even on Kubernetes — schedule it on a Docker-runtime node. The Rust usenet downloader runs off-cluster in this model.

## Podman quadlets

The leanest single-host variant: systemd-managed containers with SABnzbd as the only downloader — no nginx proxy and no Rust downloader services.

1. Copy `deployment/quadlets/*.container` to `/etc/containers/systemd/`.
2. Create `/etc/streamarr/streamarr.env` (`root:root`, mode `0600`) with the same keys as the Compose `.env` (`POSTGRES_PASSWORD`, `SECRET_KEY`, `LIGHTRAYS_JWT_SECRET`, `DOWNLOADER_WEBHOOK_SECRET`, `DATA_DIR`, `PROJECT_ROOT`). Without it the units start with empty passwords and paths.
3. `systemctl daemon-reload`, then start the units. If you start them manually, run `systemctl start streamarr-migrate.service` first.

## Database migrations

Migrations run as a dedicated **one-shot Alembic step** (`alembic upgrade head`) that executes exactly once before any app process starts — application containers do not apply migrations on boot, and no manual step is required:

- **Compose / installer**: a `migrate` service; backend, worker, and scheduler wait for it via `service_completed_successfully`.
- **Helm**: a `pre-install`/`pre-upgrade` hook Job (`migrations.enabled`, default on).
- **Quadlets**: the `streamarr-migrate.service` oneshot unit, required by the app units.

## Default ports

| Service | Port | Notes |
|---------|------|-------|
| Frontend (web UI) | `3000` | `FRONTEND_PORT` |
| Backend API | `8000` | `BACKEND_PORT`; docs at `/docs` |
| Lightrays | `8009` | Prod Compose runs it with host networking for WebRTC |
| SABnzbd | `8080` | Optional |
| Spotify / torrent / usenet downloaders | `3001` / `3002` / `3003` | Compose prod only; torrent also uses `6881/udp` |
| PostgreSQL / Elasticsearch | `5432` / `9200` | Bound to `127.0.0.1` by default |

## First start

Open `http://<your-host>:3000/install` — on a fresh installation the setup wizard walks you through creating the administrator account. Then:

1. Follow the [Quick Start](quick-start.md) to configure metadata providers and create libraries.
2. Review the [Administration Overview](../administration/overview.md) for indexers, download clients, and transcoding.
3. For architecture details, backups, and monitoring, see the [Deployment Overview](../deployment/overview.md) and [Maintenance & Backups](../administration/maintenance.md).
