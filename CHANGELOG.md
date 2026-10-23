# Changelog

All notable changes to Streamarr are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
calendar-ish versions — `year.release.patch` — see
[Releases](docs/docs/developer-guide/releases.md).

Every released version has a matching `v<version>` tag and, once published, a
GitHub Release carrying the desktop bundles and the upgrade notes. Changes that
need operator action (a migration to run, a setting to revisit) are listed under
**Upgrade notes**, not hidden in a list of fixes.

## [Unreleased]

Nothing released yet: this file starts with the first tag. The material below is
the work that landed since the project became Streamarr, grouped the way a
release note would group it. Everything before that is in `git log`.

### Upgrade notes

- **PostgreSQL `mediatype` enum.** `AUTHORS` is now part of the enum. The
  migration runs with `alembic upgrade head`; without it, `/api/trailers`,
  `/api/filters` and `/api/suggestions/autocomplete/typed` answer 500.
- **Backups.** `STREAMARR_BACKUP_DIR` defaults to `/backups`, now mounted from
  `<data>/backups` in both compose variants and a dedicated PVC in the chart.
  The shell scripts under `deployment/backup/` are gone; the archive is produced
  by the app (`POST /api/backups/disaster-recovery/pg-dump` and a nightly task).

### Added

- Media library for movies, shows, music, games, books and photos on one
  parent/child model, with TMDB/TVDB/IGDB/MusicBrainz/OpenLibrary metadata.
- Smart Play: press play on something not yet available and it is searched,
  downloaded and streamed as it arrives.
- Release automation: Newznab/Torznab indexers, quality and language scoring,
  SABnzbd and Deluge, plus built-in usenet, torrent and Spotify downloaders.
- Streaming: on-demand FFmpeg transcoding in disposable containers with Intel
  QuickSync, HLS delivery, direct-play negotiation, trickplay thumbnails,
  skip-intro markers, subtitles, lyrics and resume everywhere.
- Watch parties, Chromecast/AirPlay/DLNA casting, remote control of other
  signed-in devices, and per-device offline downloads.
- Cloud gaming through Lightrays: per-session WebRTC containers for Steam, Wine
  and RetroArch titles, playable in the browser or in the desktop app.
- Desktop app (Tauri 2) with a native mpv player, game streaming, couch mode,
  and `.deb`/`.rpm`/AppImage/NSIS/MSI bundles.
- Administration: groups and permissions, parental controls, invites, OIDC SSO,
  optional Stripe memberships, Prometheus metrics and a Grafana dashboard.
- Artwork cache with a warmup that runs after scans and hourly, so posters are
  served from disk instead of upstream.
- `automation.import_mode`: a finished download can be moved into the library
  under its final name (Sonarr/Radarr behaviour) instead of being registered
  where the downloader left it. `register` stays the default because it is right
  for rclone-backed instances, where the download folder *is* the library entry.
- Naming templates (`plugin.shows.naming.*`, `plugin.movies.naming.*`) now
  actually drive folder and file names. They were shipped as settings with
  defaults, but nothing read them: the plugins always built the built-in
  Trash-style name. A configured template wins; unset keeps the old names.

### Changed

- Seasons are imported with their own TMDB namespace (`tmdb_season`). TMDB ids
  are only unique per namespace - movie 1995 is "Lara Croft: Tomb Raider" while
  season 1995 is a Star Trek: TNG season - so a season row could answer "already
  exists" for a movie and silently block its import. Attaching an external id is
  now best-effort as well: a colliding pair no longer costs the whole import.
- Licence is MIT for the whole project.
- Seasons get their folder from `plugin.shows.naming.season_folder` instead of a
  hardcoded `Season 01`, so the folder layout can be changed in one place.
- Releases publish container images to `ghcr.io/luebke-dev/streamarr-<component>`
  and `latest` follows release tags only, not the default branch.

### Fixed

- A library scan no longer registers a second `media_file` row for a path it
  already knows. An import that moves a file into the library could be scanned
  while the copy was still running, which left a duplicate row next to the real
  one (a 35 MB placeholder beside the finished 3.4 GB file).
- Promotion to the library uses the library path from the database instead of the
  built-in `/library/...` default, and records provenance: `imported_at`,
  `library_guid` and `library_root` are set when a file is moved, so a promoted
  file no longer looks like a download that was never imported.
- Episode acquisition works again. When the hierarchy got its own `SEASONS` and
  `EPISODES` types, several places kept listing only `MOVIES`/`SHOWS`: the release
  search skipped every episode, the dispatcher rejected them as unsupported, the
  show context resolved no season/episode numbers, and no library plugin parsed
  the release - which left every candidate at "480p" and the quality profile
  rejected it. No episode could be grabbed, by RSS, by the sweep or by hand.
- RSS sync polls the feed with a category filter (movies and shows) instead of the
  indexer's global newest items. On a general-purpose indexer the unfiltered feed
  is almost entirely software, so no monitored title could ever match. The window
  is configurable via `automation.rss_feed_limit` (default 100).
- An RSS hit now acquires the release it announces: the feed title is parsed for
  its season/episode and only that leaf is searched. Previously a single new
  episode triggered a backfill of the whole show, which queued every missing
  episode at once (a 13-season series would have queued its entire backlog).
- Episode downloads are no longer rejected as "wrong content" when the episode
  title is localized. The import guard compared the German title
  ("Freiheitstag") with the English release name ("Silo.S01E01.German...") and
  found no overlap; it now compares show title plus SxxExx, and SxxExx tokens no
  longer count as title tokens - otherwise two different shows looked identical.
- Importing a title by TMDB id no longer fails because of a genre. Imports that
  only see numeric genre ids tried to link genres the local table did not know,
  the foreign-key violation aborted the transaction and the swallowed error made
  every following statement fail - 39 of 87 titles could not be imported at all.
  Unknown genres are skipped and the risky writes run inside savepoints.
- Transcoding: a finished encode is no longer mistaken for a crash and restarted
  from the beginning, which had been overwriting the segments a player was
  reading (the "stream stalls every few minutes" symptom) and leaving 4.5 GB of
  duplicated segments per episode.
- Transcoding: the configured bitrate and quality now reach hardware encoders;
  before, both settings were ignored on any QSV host.
- Playback: codecs MPEG-TS cannot carry (AV1, VP9, Opus, FLAC) are no longer
  direct-copied into HLS, which used to produce a valid playlist no browser
  could play.
- Playback: a dead session no longer holds a transcode slot until the next
  six-hourly sweep, and a session's segments are removed when it ends instead of
  accumulating in `/temp`.
- Media: episodes resolve their show hierarchy, so a series no longer renders as
  `· SnullEnull`, and episode metadata refreshes use the right plugin.
- Artwork: the poster hot path caches, rate-limits on cache misses only, and no
  longer resolves DNS synchronously per image.
- Backup: the `pg_dump` path works (client tools in the image, a writable
  archive volume) instead of failing with a permission error.
- Database: the `mediatype` enum knows `AUTHORS`, which three endpoints and the
  home page needed.
