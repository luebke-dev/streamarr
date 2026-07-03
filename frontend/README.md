# pyrate.media — Frontend

Vue 3 / Quasar SPA for the pyrate.media self-hosted media server.

## Stack

- **Vue 3** with Composition API (`<script setup>`)
- **Quasar 2** — UI framework (dark mode, Material Design Icons)
- **Vite** — build tooling
- **Pinia** — state management
- **Video.js 8** — HLS playback with sprite thumbnails
- **vue-i18n** — English and German locales
- **Tauri 2** — desktop shell for Linux, macOS, and Windows

## Features

- **Media browsing** — hero carousel, genre sections, trending lists, search
- **Playback** — HLS streaming with codec negotiation, quality selection, trickplay scrubbing
- **Watch parties** — synchronized playback with WebSocket sync
- **Library management** — per-library settings, scoring config, naming rules
- **Admin panel** — indexers, downloaders, transcoding, users, groups, downloads, tasks
- **Release management** — search, score, download, blacklist, delete
- **Lists** — user lists, favorites, trending, likes, follows
- **Remote control** — control playback across devices
- **Responsive** — mobile, tablet, desktop layouts

## Quick Start

```bash
yarn install
yarn dev          # dev server on :9000, proxies /api to :8000
yarn dev:tauri    # desktop app against the same dev server
```

## Commands

```bash
yarn dev            # development server with hot reload
yarn dev:tauri      # Tauri desktop development
yarn build          # production build
yarn build:tauri    # production desktop bundles
yarn test:unit      # run tests (Vitest + happy-dom)
yarn test           # tests in watch mode
yarn lint           # ESLint
yarn format         # Prettier
```

## Project Structure

```
src/
  boot/           axios (auto-auth), video.js, websocket, i18n
  components/     reusable UI — HeroCarousel, MediaReleasesTable, ScoringConfigPanel, ...
  composables/    usePlay, useWebSocket, useWatchPartyWebSocket, useMediaHelpers, ...
  i18n/           en-US, de-DE locale files
  layouts/        MainLayout (sidebar nav), AuthLayout, AdminLayout
  pages/          PlayPage, MediaDetailPage, SearchResultsPage, admin/*, ...
  stores/         auth, watchParty, remoteControl, audioPlayer (Pinia)
  utils/          logger
src-tauri/
  capabilities/   Tauri window permissions
  src/            Rust desktop entrypoint
  tauri.conf.json desktop build and bundle config
```

## Key Patterns

- **Axios** auto-injects auth headers and refreshes tokens on 401 (`boot/axios.js`)
- **WebSocket** singleton with auto-reconnect, channel subscriptions, Redis pub/sub bridge (`boot/websocket.js`)
- **Playback** detects client codecs, negotiates with backend, falls back to transcoding (`composables/usePlay.js`)
- **Real-time updates** — releases, downloads, files update via WebSocket events on MediaDetailPage
- **Scoring config** — admin sliders for resolution, source, codec, audio, language weights per library type

## License

Proprietary. All rights reserved.
