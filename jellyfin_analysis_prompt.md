# Agent Prompt: Jellyfin → pyrate.media feature gap analysis

**Goal**: Survey all user-facing functionality in the Jellyfin reference codebase, compare against the current pyrate.media implementation, and write a gap analysis to `/root/pyrate.media/JELLYFIN_FEATURE_ANALYSIS.md`.

## Context

- pyrate.media is an in-progress media server at `/root/pyrate.media/`.
  - Backend (Python): `/root/pyrate.media/backend/src/` — look for routers/endpoints.
  - Frontend (Quasar/Vue): `/root/pyrate.media/frontend/src/` — look for pages/components.
  - Other top-level dirs: `downloaders/`, `deployment/`, `lightrays/`.
- Jellyfin reference (C#/.NET) at `/root/pyrate.media/references/jellyfin/`. Mature project; pyrate is young.

## Definition of "user-facing" (analyze)

- Library management (movies, shows, music, photos, books), scanning, refresh.
- Playback: transcoding, subtitles, audio tracks, resume, seek, chapters, direct play vs. transcode.
- Metadata & artwork (scrapers, manual override, identification).
- Users/accounts/profiles, permissions, parental controls, auth providers.
- Collections, playlists, favorites, watch history, "next up".
- Search & filtering, genres, recommendations.
- Sync/download to device, offline playback.
- Live TV / DVR, channels, recordings.
- Casting/streaming (Chromecast, DLNA, AirPlay).
- Client/app integrations, remote control sessions.
- Notifications, plugins, themes, custom branding.
- Admin/server: storage paths, scheduled tasks, logs, transcoding settings, network, SSL.

**Out of scope**: internal-only APIs, DB internals, build/CI, C#-specific implementation details.

## Method

1. Walk `references/jellyfin/Jellyfin.Api/Controllers/` — each controller ~ one feature area. Cross-reference with `references/jellyfin/MediaBrowser.Model/` for the feature surface. Skim `README.md` for high-level claims.
2. Walk pyrate's `backend/src/` (find routers/endpoints) and `frontend/src/` (pages/components/stores) to map what exists.
3. For each feature area, classify as: **Implemented** / **Partial** / **Missing** / **Not applicable**. For Partial/Missing, write 1–3 sentences on what's needed. For Implemented, note obvious improvement opportunities if any.

## Output file

Write to `/root/pyrate.media/JELLYFIN_FEATURE_ANALYSIS.md` with this structure:

1. Short intro (scope, method, date 2026-05-11).
2. Summary table: feature area | Jellyfin has? | pyrate status | note.
3. Detailed sections per feature area, with citations like `Jellyfin.Api/Controllers/ItemsController.cs` and `backend/src/.../media.py`.
4. "Top priorities" — ranked list of ~10 highest-impact gaps to close in pyrate, each with one-sentence rationale (impact × effort).

## Constraints

- Read-only — do not modify source code, do not clone or fetch more repos.
- If uncertain, write "needs verification" instead of guessing.
- Keep the file under ~800 lines; concise but specific. Cite file paths.
- Write the analysis in English (matches the codebase).
