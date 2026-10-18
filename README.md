<p align="center">
  <img src="docs/docs/assets/logo.png" width="120" alt="Streamarr logo"/>
</p>

<h1 align="center">Streamarr</h1>
<h3 align="center">Your media, your rules.</h3>

---

Streamarr is a self-hosted home for your media. It keeps your movies and shows, music, games, books and photos in one library, plays them on whatever screen you happen to be sitting in front of, and quietly takes care of the fetching, sorting and metadata in the background.

The usual way there is a pile of applications that each want their own library, their own users and their own passwords: a media server here, a release manager there, a game-streaming setup on top. Streamarr is one application instead — one library, one user system, one interface.

It runs on your own hardware, and nobody else has a say in it: no subscription, no licence tiers, no telemetry.

**Want to get started?** The installer does the rest on a fresh Linux box:

```bash
curl -fsSL https://get.streamarr.media | sudo bash
```

It installs Docker, generates the secrets, and starts the stack. Setting things up by hand is just as supported — Docker Compose, Kubernetes (Helm), and Podman quadlets all live in [`deployment/`](deployment/). The [quick start](https://streamarr.luebke.dev/getting-started/quick-start/) then walks you through the setup wizard, your first library, and indexers.

**Documentation:** <https://streamarr.luebke.dev>

**Something broken, or an idea?** [Open an issue](https://github.com/luebke-dev/streamarr/issues).

## What's inside

- **Six kinds of media, one library.** Movies and shows, music, games, books, photos — the same search, the same users, the same lists.
- **Press play on something you don't have yet.** It searches your indexers, downloads it, and starts streaming while you wait.
- **Downloads that keep up.** New releases for what you follow, quality upgrades, RSS, ranked by the quality and languages you actually want.
- **Every screen you own.** Web, desktop (Linux, macOS, Windows), Android. Direct play where the device can handle it, transcoding where it can't, Chromecast/AirPlay/DLNA, and downloads for offline.
- **Watch together.** Synchronised watch parties with a six-digit code, plus remote control for the other screens in the house.
- **Games, streamed from your own server.** Steam, Wine and RetroArch titles start in a session and play in the browser.
- **Good neighbours.** Invite-based accounts, groups, parental controls, optional memberships, and an admin UI for every part of the system.

The interface is available in English and German. For a feature-by-feature tour, see the [documentation](https://streamarr.luebke.dev).

## Development

The whole stack builds from the repository root — after a `.env` with at least `SECRET_KEY`, `DATABASE_URL` and `REDIS_URL`:

```bash
docker compose up -d --build
```

Backend is Python (FastAPI) with background workers, frontend is Vue/Quasar, and the downloader and game-streaming services are Rust. The [developer guide](https://streamarr.luebke.dev/developer-guide/overview/) covers running the parts individually, the monorepo layout, tests, and linting.

Secrets are never committed; each subproject ships its own `.env.example` template.

## License

Proprietary. All rights reserved.
