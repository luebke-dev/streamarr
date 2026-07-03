# Frontend Architecture Review Findings

Date: 2026-05-11
Scope: `frontend/src` static review plus `npm run lint`
Lint status: passing

This document is intended as a goal-loop input for an implementation agent.
It lists concrete frontend bad practices, anti-patterns, refactor candidates,
and acceptance criteria.

## Executive Summary

The frontend is functional and lint-clean, but several areas have grown past
reasonable component boundaries. The highest-risk issues are not style issues:

- Admin routes are not marked as admin-only in router metadata.
- The current-device identity uses inconsistent localStorage keys.
- `MediaDetailPage.vue` is a god component with page rendering, data access,
  admin operations, WebSocket reconciliation, and delayed reload logic mixed
  together.
- API calls are scattered across pages/components instead of flowing through a
  consistent service/composable layer.
- Several reusable form/table patterns exist but are duplicated or hardcoded.

## Findings

### 1. Admin routes are not frontend-guarded as admin-only

Severity: High

Evidence:

- `frontend/src/router/routes.js:161` defines the `/admin` route without
  `meta.requiresAdmin`.
- `frontend/src/router/index.js:55` only checks admin access when a matched
  route has `meta.requiresAdmin === true`.
- `frontend/src/components/UserMenu.vue:74` hides the Admin menu item for
  non-admin users, but direct URL navigation is not blocked by the frontend.

Impact:

Non-admin users can navigate to admin frontend pages directly. Backend
authorization may still protect data, but the frontend guard is inconsistent
and can expose broken/empty admin UI.

Recommended fix:

Add `meta: { requiresAuth: true, requiresAdmin: true }` to the `/admin` parent
route or all admin child routes. Keep backend authorization as the source of
truth.

Acceptance criteria:

- A non-admin authenticated user navigating to `/admin` is redirected.
- An admin user can still access all admin routes.
- No auth route behavior regresses.

Validation:

- Add/adjust router guard tests if available.
- Manually test `/admin`, `/admin/users`, `/admin/settings` with admin and
  non-admin sessions.

### 2. Device ID localStorage key mismatch

Severity: High

Evidence:

- `frontend/src/stores/auth.js:7` defines `DEVICE_ID_KEY = 'pyrate_device_id'`.
- `frontend/src/composables/useWebSocket.js:30` also uses `pyrate_device_id`.
- `frontend/src/components/user-settings/DevicesSection.vue:215` reads
  `localStorage.getItem('device_id')`.

Impact:

The settings Devices section may fail to identify the current device, causing
wrong current-device badges/actions or confusing device removal behavior.

Recommended fix:

Extract a shared `deviceIdentity` utility or export the key from one source.
Update `DevicesSection` to use the same `pyrate_device_id` key.

Acceptance criteria:

- Current device is correctly marked in user settings.
- WebSocket URL still includes the expected device id.
- No duplicate device IDs are generated after reload/login.

Validation:

- Check localStorage contains exactly the expected key.
- Open user settings Devices section and verify the current device marker.

### 3. `MediaDetailPage.vue` is a god component

Severity: High

Evidence:

- `frontend/src/pages/MediaDetailPage.vue` is about 2028 lines.
- Imports, state, computed media classification, playback actions, favorite
  state, admin file/release operations, provider repair, artwork upload,
  downloads, availability polling, and WebSocket subscription handling are all
  in one page file.
- API-heavy section starts around `frontend/src/pages/MediaDetailPage.vue:1303`.
- WebSocket/availability cleanup lives around
  `frontend/src/pages/MediaDetailPage.vue:1699`.

Impact:

The page is hard to change safely. Small feature work risks breaking unrelated
areas like availability polling, admin tables, or provider repair flows.

Recommended extraction:

- `useMediaDetailPage(guidRef)` for core load/reset/route state.
- `useMediaAvailability(mediaItemRef)` for availability, watch toggle,
  WebSocket target subscriptions, retry polling.
- `useMediaAdminActions(mediaItemRef)` for releases, files, downloads, reprobe,
  delete, search.
- `useMediaProviderRepair(mediaItemRef)` for subtitles, lyrics, artwork search,
  artwork upload.
- Components:
  - `MediaChildrenSection.vue`
  - `MediaProviderRepairPanel.vue`
  - `MediaAdminPanel.vue`
  - possibly `MediaExternalLinks.vue`

Acceptance criteria:

- `MediaDetailPage.vue` becomes mostly composition/orchestration and template.
- Provider repair and admin operations are testable without mounting the whole
  page.
- Route change and unmount cleanup behavior remains intact.
- No change to user-visible behavior.

Validation:

- `npm run lint`
- `npm run test:unit` if tests exist/pass locally.
- Manual: open movie, show, season, episode, artist, album, song, game, book
  detail pages.

### 4. Untracked timers in `MediaDetailPage.vue`

Severity: Medium

Evidence:

Untracked `setTimeout` reloads:

- `frontend/src/pages/MediaDetailPage.vue:1306`
- `frontend/src/pages/MediaDetailPage.vue:1362`
- `frontend/src/pages/MediaDetailPage.vue:1394`
- `frontend/src/pages/MediaDetailPage.vue:1554`

Cleanup only clears `availabilityRetryTimer`:

- `frontend/src/pages/MediaDetailPage.vue:1778`

Impact:

If the user navigates away quickly, delayed callbacks can run after route
change/unmount and write stale data into the wrong page instance.

Recommended fix:

Use a small `useTimeoutRegistry`/`useDelayedRefresh` composable or a local
timer set that is cleared on unmount and before route reload.

Acceptance criteria:

- All delayed callbacks are registered and cleared on unmount.
- Route changes cancel pending refreshes for the old media item.

Validation:

- Manual: trigger release search/reprobe/metadata refresh, immediately navigate
  to another item, confirm no stale update or console error.

### 5. API calls are scattered across views and components

Severity: Medium

Evidence:

Direct `api` imports appear throughout pages/components, for example:

- `frontend/src/pages/MediaDetailPage.vue:554`
- `frontend/src/pages/PlayPage.vue:118`
- `frontend/src/pages/admin/SettingsPage.vue:460`
- `frontend/src/pages/UserSettingsPage.vue:487`
- many `frontend/src/components/sections/*Section.vue`

Impact:

Backend endpoint knowledge is duplicated throughout UI code. Error handling,
response normalization, caching, and retries cannot be changed centrally.

Recommended fix:

Introduce service modules under `src/services` or endpoint-specific composables:

- `mediaService`
- `authService`
- `settingsService`
- `devicesService`
- `pageLayoutService`
- `adminService` or smaller admin domain services

Keep `boot/axios.js` as transport/interceptor only.

Acceptance criteria:

- New feature code does not import `api` directly from page components unless
  there is a strong reason.
- Existing high-churn areas (`MediaDetailPage`, settings, devices) use services.
- Services normalize response shapes where backend inconsistencies exist.

Validation:

- `grep -R "import { api }" frontend/src/pages frontend/src/components`
  count decreases for migrated areas.

### 6. Auth, token, and server URL storage are too distributed

Severity: Medium

Evidence:

- `frontend/src/boot/axios.js:36` reads `access_token`.
- `frontend/src/stores/auth.js:97` writes tokens.
- `frontend/src/pages/auth/RegisterPage.vue:447` writes tokens directly.
- `frontend/src/composables/useWebSocket.js:61` reads `access_token`.
- `frontend/src/composables/useViewingProgress.js:116` reads `access_token`.
- Server URL is read/written in multiple places.

Impact:

Auth behavior is harder to audit. Token changes, logout behavior, and device
identity can drift between modules.

Recommended fix:

Create `src/utils/authStorage.js` and `src/utils/deviceIdentity.js`, or move
all token/device storage behind the auth store. Pages should call auth-store
actions instead of writing tokens directly.

Acceptance criteria:

- `RegisterPage` uses `authStore.saveTokensToStorage` or a register action.
- `useWebSocket`, Axios boot, and `useViewingProgress` use shared helpers.
- No duplicate key strings for token or device identity remain outside one
  module.

Validation:

- `grep -R "access_token\\|refresh_token\\|pyrate_device_id\\|device_id"`
  shows only expected centralized definitions plus reads through helpers.

### 7. `SectionConfigDialog.vue` should be schema/component driven

Severity: Medium

Evidence:

- `frontend/src/components/sections/SectionConfigDialog.vue` is about 736 lines.
- Filter form fragments are repeated for hero carousel, list/all-genres, and
  dynamic search:
  - `frontend/src/components/sections/SectionConfigDialog.vue:35`
  - `frontend/src/components/sections/SectionConfigDialog.vue:234`
  - `frontend/src/components/sections/SectionConfigDialog.vue:353`
- Options and labels are hardcoded at
  `frontend/src/components/sections/SectionConfigDialog.vue:641`.

Impact:

Adding a section type or filter requires editing a large template. Translation
coverage is inconsistent because many labels/hints are inline strings.

Recommended fix:

Create:

- `sectionConfigRegistry.js` mapping section types to defaults, labels, and
  form component.
- Smaller form components:
  - `HeroCarouselConfigForm.vue`
  - `DynamicSearchConfigForm.vue`
  - `ListSectionConfigForm.vue`
  - `LatestItemsConfigForm.vue`
  - `ContinueWatchingConfigForm.vue`
- Shared `MediaFiltersForm.vue` for common filters.

Acceptance criteria:

- `SectionConfigDialog.vue` contains dialog shell, section selector, save
  behavior, and delegates the active config form.
- Shared filter fields are defined once.
- Hardcoded user-facing English is moved to i18n or central option builders.

Validation:

- Open page layout editor and create/edit every section type.

### 8. Duplicate files/releases table components

Severity: Medium

Evidence:

- `frontend/src/components/MediaReleasesTable.vue`
- `frontend/src/components/admin/MediaReleasesTable.vue`
- `frontend/src/components/MediaFilesTable.vue`
- `frontend/src/components/admin/MediaFilesTable.vue`

Impact:

Similar visual and formatting logic can drift. Component names are easy to
confuse in imports.

Recommended fix:

Create generic presentational pieces:

- `MediaFilesTableBase.vue`
- `MediaReleasesTableBase.vue`

Then use slots/props for admin-only actions such as reprobe, delete, download,
delete-all.

Acceptance criteria:

- Shared columns/formatters are centralized.
- Admin variants are thin wrappers or slots over the base table.
- Import names are unambiguous.

Validation:

- Manual compare media detail admin/non-admin file and release sections.

### 9. `PlayPage.vue` still orchestrates too many playback domains

Severity: Medium

Evidence:

- `frontend/src/pages/PlayPage.vue` is about 1111 lines.
- It orchestrates media loading, music shortcut, Lightrays launch, book reader,
  video setup, playlist navigation, party sync, remote control, player events,
  stream readiness, song identification, and route cleanup.
- Entry point around `frontend/src/pages/PlayPage.vue:415`.
- Lightrays launch around `frontend/src/pages/PlayPage.vue:479`.
- Lifecycle/cleanup around `frontend/src/pages/PlayPage.vue:955`.

Impact:

Playback changes are risky because unrelated playback domains share one file.

Recommended extraction:

- `usePlaybackBootstrap`
- `usePlaylistNavigation`
- `useGameLaunch`
- `useBookPlayback`
- `useSongIdentification`
- Possibly a `PlaybackStateProvider` using `provide/inject` for player controls.

Acceptance criteria:

- `PlayPage.vue` is mostly routing/status rendering and delegates domain logic.
- Game/book/video paths are independently testable.
- Cleanup semantics are explicit and covered by composable teardown.

Validation:

- Manual: movie playback, episode next/previous, playlist playback, book reader,
  game stream launch, song identification.

### 10. `CustomPlayerControls.vue` has a broad prop/event surface

Severity: Low/Medium

Evidence:

- Props span player refs, content metadata, stream metadata, navigation state,
  favorite state, and identifying state around
  `frontend/src/components/CustomPlayerControls.vue:292`.
- Emits span seek, tracks, playback, volume, fullscreen, nav, favorite, quality,
  identify, report around `frontend/src/components/CustomPlayerControls.vue:394`.

Impact:

Parent/child coupling is high. Adding a new player control requires changing
both `PlayPage` and `CustomPlayerControls`.

Recommended fix:

Group state into stable objects:

- `playerState`
- `navigationState`
- `streamState`
- `mediaActions`

Or use `provide/inject` for player chrome if the player subtree grows.

Acceptance criteria:

- Controls component has fewer primitive props.
- Event naming is grouped and easier to reason about.

### 11. User-facing strings and option lists are duplicated/hardcoded

Severity: Low/Medium

Evidence:

- Hardcoded English labels in `SectionConfigDialog.vue:641`.
- Language option lists duplicated in:
  - `frontend/src/pages/UserSettingsPage.vue:543`
  - `frontend/src/pages/auth/RegisterPage.vue:335`
  - `frontend/src/components/admin/UserBasicInfoForm.vue:132`
- Hardcoded fallback strings such as `Unknown`, `Blacklisted`, `Last searched`
  in table components.

Impact:

Translations drift. Option sets differ between registration, profile, and admin
forms.

Recommended fix:

Centralize language options and UI option builders in `src/utils` or
`src/i18n/options.js`. Move table fallback strings to i18n.

Acceptance criteria:

- UI language/media language/subtitle language options are defined once.
- No new hardcoded user-facing strings in migrated components.

### 12. Mixed Vue API styles remain in newer areas

Severity: Low

Evidence:

Most files use `<script setup>`, but several sizeable components/pages still use
Options API or `defineComponent`, including:

- `frontend/src/pages/MediaDetailPage.vue`
- `frontend/src/pages/admin/IndexerFormPage.vue`
- `frontend/src/components/HeroCarousel.vue`
- `frontend/src/components/PosterCard.vue`
- `frontend/src/components/admin/MediaFilesTable.vue`
- `frontend/src/components/admin/MediaReleasesTable.vue`

Impact:

This is not a bug, but it increases local style variance and makes shared
patterns harder to apply.

Recommended fix:

Do not mass-convert blindly. Convert files opportunistically when extracting
logic or touching them for real changes.

## Suggested Goal Loop Plan

### Goal 1: Fix access and identity correctness

Objective:

Close the two concrete correctness issues before larger refactors.

Tasks:

- Add admin route metadata.
- Verify router guard behavior.
- Centralize device identity key.
- Update `DevicesSection` to use shared device identity.

Acceptance:

- Non-admin direct `/admin` navigation is blocked.
- Current device is correctly detected.
- Lint passes.

### Goal 2: Stabilize `MediaDetailPage` timers and split low-risk composables

Objective:

Reduce state-leak risk without changing UI.

Tasks:

- Add a timer registry composable.
- Replace untracked `setTimeout` calls.
- Extract availability/watch logic to `useMediaAvailability`.
- Extract admin file/release/download operations to `useMediaAdminActions`.

Acceptance:

- Pending delayed refreshes are cleaned up on route change/unmount.
- Behavior remains the same for releases/files/availability.
- `MediaDetailPage.vue` line count drops meaningfully.

### Goal 3: Extract provider repair and admin panel UI from `MediaDetailPage`

Objective:

Make provider repair and admin tools independently maintainable.

Tasks:

- Create `MediaProviderRepairPanel.vue`.
- Create `useMediaProviderRepair`.
- Create `MediaAdminPanel.vue` to compose files/releases/downloads/markers.

Acceptance:

- `MediaDetailPage` no longer contains subtitle/lyrics/artwork API details.
- Admin panels are isolated behind props/events or composables.

### Goal 4: Introduce service layer for high-churn domains

Objective:

Move endpoint knowledge out of views.

Tasks:

- Create `src/services/mediaService.js`.
- Create `src/services/settingsService.js`.
- Create `src/services/deviceService.js`.
- Migrate current touched areas first; avoid broad churn.

Acceptance:

- Direct `api` imports in migrated pages/components are gone.
- Service methods have consistent names and response normalization.

### Goal 5: Refactor section config forms

Objective:

Turn `SectionConfigDialog` into a maintainable registry-driven dialog.

Tasks:

- Create section config registry.
- Extract shared `MediaFiltersForm.vue`.
- Extract section-specific config form components.
- Move labels/options to i18n or central option builders.

Acceptance:

- Adding a section type does not require editing a 700-line template.
- Existing section create/edit flows still work.

### Goal 6: Consolidate table and option duplication

Objective:

Reduce UI drift in files/releases and language/options.

Tasks:

- Create base table components for media files and releases.
- Convert admin wrappers to use base components.
- Centralize language/quality/filter options.

Acceptance:

- Duplicate table formatting logic is removed.
- Option lists are defined once where feasible.

### Goal 7: Continue playback decomposition

Objective:

Make playback domains independently changeable.

Tasks:

- Extract game launch to `useGameLaunch`.
- Extract book playback setup to `useBookPlayback`.
- Extract song identification to `useSongIdentification`.
- Consider grouped state objects for `CustomPlayerControls`.

Acceptance:

- `PlayPage.vue` owns route/status orchestration, not all domain logic.
- Manual playback scenarios still pass.

## Non-Goals

- Do not rewrite the whole frontend in one pass.
- Do not convert all Options API files just for consistency.
- Do not change UI styling unless needed for component boundaries.
- Do not move every API call immediately; migrate by domain as files are touched.

## Validation Checklist

Run after each goal:

```bash
npm run lint
```

Run when feasible:

```bash
npm run test:unit
npm run build
```

Manual smoke checks:

- Login/logout/register callback still work.
- Frontend route `/`, `/movies`, `/shows`, `/settings`, `/admin`.
- Media detail for at least one movie and one show episode.
- Admin settings, users, devices, lists.
- Playback for one video item.

