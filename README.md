# pyrate.media — Monorepo

Zusammenführung der zuvor getrennten pyrate.media-Repositories in ein Monorepo.
Dieser Import ist ein **Snapshot** des jeweils aktuellen Standes (kein History-Merge);
die vollständige Historie der Einzelprojekte bleibt in den ursprünglichen GitLab-Repos erhalten.

## Struktur

| Pfad | Beschreibung | Ursprung (GitLab) |
|------|--------------|-------------------|
| `backend/` | API-/Media-Server-Backend (Python) | `pyrate.media/backend` |
| `frontend/` | Web-/App-Frontend (Quasar/Vue, Tauri, Capacitor) | `pyrate.media/frontend` |
| `lightrays/` | Lightrays-Dienst (Rust) | `pyrate.media/lightrays` |
| `downloaders/torrent/` | Torrent-Downloader | `pyrate.media/downloaders/torrent` |
| `downloaders/spotify/` | Spotify-Downloader | `pyrate.media/downloaders/spotify` |
| `downloaders/usenet/` | Usenet-Downloader (Rust) | `pyrate.media/downloaders/usenet` |
| `deployment/` | Deployment (Helm, Docker, Quadlets) | `pyrate.media/deployment` |
| `docs/` | Projektdokumentation | `pyrate.media/docs` |
| `observability/` | Grafana / Monitoring-Konfiguration | (vorher nicht versioniert) |
| `docker-compose.yml` | Lokale Orchestrierung aller Dienste | Projekt-Root |

## Bewusst NICHT enthalten

- `references/` — fremde Referenz-Repos (jellyfin, sonarr, radarr, sabnzbd)
- `data/` — Laufzeit-/Mediendaten (~64 GB)
- Secrets: `.env`, `pyrate-release.keystore` u. ä. (siehe `.gitignore`)

## Lokale Konfiguration

Secrets werden nicht eingecheckt. Lege die benötigten `.env`-Dateien anhand der
jeweiligen `.env.example` in den Unterprojekten an.
