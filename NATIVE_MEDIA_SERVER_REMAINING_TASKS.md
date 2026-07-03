# pyrate Native Media Server Remaining Tasks

Stand: 2026-05-11

Diese Datei ist als Uebergabe fuer einen weiteren Agenten gedacht. Ziel ist,
offene Media-Server-Parity-Punkte weiter umzusetzen, aber strikt nativ in
pyrate. Keine fremden Produktnamen, keine kopierten Controller-Namen, keine
Shim-/Adapter-Routensysteme und keine zweiten Systeme neben bestehenden pyrate
Ownern.

## Aktueller Stand

Backend `main` ist derzeit bei:

- `cb87549 Expose native device session contracts`

Frontend `main` ist derzeit bei:

- `52a03af Use native device session controls`

Zuletzt umgesetzt:

- Native Device-Session-Contracts in `backend/src/pyrate/api/v1/devices.py`.
- Remote-Control fuer pyrate Geraete ueber native `/api/devices/by-id/{device_id}/...` Endpoints.
- Admin-Geraeteseite mit Session-Dialog ueber `/api/devices/{device_guid}/session`.
- Erweiterte Suche/Filter im bestehenden Such-Frontend.

## Harte Regeln

1. Vor jeder Implementierung Owner suchen.
   - Gibt es bereits ein pyrate Modul, eine Route, einen Service, ein Schema,
     ein Model, einen Store oder eine UI fuer die Domaene, dann dort erweitern.
   - Neue Dateien nur erstellen, wenn es wirklich keinen bestehenden pyrate
     Owner gibt.

2. Keine fremden API-Formen kopieren.
   - Keine Routen nur fuer andere Client-URLs.
   - Keine fremden Payload-Namen.
   - Keine Grossbuchstaben in Backend-Route-Pfaden.
   - Keine Route-Aliase fuer fremde Clients.

3. Native pyrate Benennung einhalten.
   - Backend-Routen: lowercase, kebab-case oder bestehende pyrate-Konvention.
   - Python-Felder: snake_case.
   - Frontend-Aufrufe: native `/api/...` pyrate Endpoints.

4. Vor Merge immer Audit laufen lassen.
   - Falls ein Audit-Treffer echt ist: nicht mergen, erst integrieren oder
     entfernen.
   - Begriffe fuer externe Referenzprodukte lokal als Shell-Variable setzen,
     diese Datei schreibt sie absichtlich nicht aus.

Empfohlener Audit von `/root/pyrate.media`:

```bash
FORBIDDEN_NAMES_REGEX='external_product_name|copied_controller_name|foreign_payload_name|foreign_route_name'

grep -RInE "$FORBIDDEN_NAMES_REGEX" backend/src frontend/src backend/tests frontend/test || true

grep -RInE '@router\.(get|post|put|delete|patch)\("[^"]*[A-Z][^"]*"' \
  backend/src/pyrate/api frontend/src || true

find backend/src frontend/src backend/tests frontend/test \
  \( -iname '*foreign*' -o -iname '*shim*' -o -iname '*startup*' \
     -o -iname '*user_views*' -o -iname '*music_genres*' \
     -o -iname '*notification_dispatch*' \) -print

git -C backend diff --check
git -C frontend diff --check
```

## 1. Frontend Test-Baseline reparieren

Prioritaet: hoch, weil die komplette Vitest-Suite aktuell nicht gruenn ist.

Aktuelle bekannte Fehler aus `npm test -- --run`:

- `frontend/test/vitest/composables/useFormatters.spec.js`
- `frontend/test/vitest/composables/useMediaFormatters.spec.js`
- `frontend/test/vitest/composables/useMediaHelpers.spec.js`
- `frontend/test/vitest/stores/auth.store.spec.js`
- `frontend/test/vitest/stores/watchParty.store.spec.js`

Umsetzung:

1. Fuer Formatter zuerst die gewuenschte UI-Konvention festlegen.
   - Player-Zeitwerte sollten `0:00` oder `--:--` nutzen, aber nicht je Datei
     unterschiedlich.
   - Laufzeit/Metadaten-Anzeigen koennen menschenlesbare Werte wie `1h 20m`
     behalten, falls diese im UI verwendet werden.
   - Danach Tests und Implementierung angleichen.

2. Auth-Store-Test aktualisieren.
   - Aktueller Store nutzt `audioLanguages` als Array.
   - Alte Tests erwarten `audioLanguage`.
   - Nicht wieder einen alten Getter nur fuer Tests einfuehren, wenn das UI
     bereits auf `audioLanguages` arbeitet.

3. Party-Store-Test korrigieren.
   - Kein zweiter Store erstellen.
   - Bestehender Owner ist `frontend/src/stores/party.js`.
   - Testimport und Erwartungen auf diesen Store anpassen.

Definition of Done:

```bash
cd /root/pyrate.media/frontend
npm run lint
npm test -- --run
```

## 2. Native Session- und Playstate-UX ausbauen

Prioritaet: hoch. Backend-Grundlage existiert, UI kann noch mehr daraus machen.

Bestehende Owner:

- Backend: `backend/src/pyrate/api/v1/devices.py`
- Backend: `backend/src/pyrate/api/v1/viewing_history.py`
- Backend: `backend/src/pyrate/services/websocket.py`
- Frontend: `frontend/src/stores/remoteControl.js`
- Frontend: `frontend/src/components/RemoteControlButton.vue`
- Frontend: `frontend/src/pages/admin/DevicesPage.vue`
- Frontend: `frontend/src/pages/admin/SessionsPage.vue`
- Frontend: `frontend/src/pages/PlayPage.vue`

Umsetzung:

1. `SessionsPage.vue` mit Device-Session-Contract verbinden.
   - Von aktiver Session aus zu `/api/devices/{device_guid}/session` laden.
   - Now-playing, Queue, Capabilities und letzte Commands anzeigen.
   - Keine neue Admin-Seite erstellen, bestehende Sessions-Seite erweitern.

2. Remote-Control Capability-gesteuert machen.
   - Buttons deaktivieren, wenn `capabilities.supported_commands` den Command
     nicht enthaelt.
   - Volume nur anzeigen, wenn `supports_volume_control` wahr ist oder das
     Ziel ein vorhandenes natives Cast-Ziel mit Volume-Support ist.
   - Queue-Buttons nur anzeigen, wenn `supports_play_queue` wahr ist.

3. Session Message UI ergaenzen.
   - Kleines Dialogfeld im Remote-Control-Menue fuer `message`.
   - Store soll vorhandenen Endpoint
     `/api/devices/by-id/{device_id}/message` nutzen.
   - Keine neue Message-Route anlegen.

4. Playstate im Player sauberer zurueckmelden.
   - `PlayPage.vue` soll bei Start/Progress/Stop die bestehenden nativen
     Playstate-Endpunkte konsistent nutzen.
   - Vorher `viewing_history.py` und bestehende Composables pruefen.

Tests:

```bash
cd /root/pyrate.media/frontend
npx eslint src/stores/remoteControl.js src/components/RemoteControlButton.vue src/pages/admin/SessionsPage.vue src/pages/PlayPage.vue
npm test -- --run test/vitest/stores/remoteControl.store.spec.js

cd /root/pyrate.media/backend
python3 -m py_compile src/pyrate/api/v1/devices.py src/pyrate/api/v1/viewing_history.py
python3 -m pytest tests/api/test_devices_api.py tests/api/test_viewing_history_api.py -q
```

Wenn `pytest` fehlt, nicht ignorieren: im Abschluss klar notieren.

## 3. Cast-Protokolle vertiefen

Prioritaet: hoch fuer Wohnzimmer-Nutzung.

Bestehende Owner:

- Backend: `backend/src/pyrate/api/v1/cast.py`
- Frontend: `frontend/src/components/RemoteControlButton.vue`
- Frontend: `frontend/src/pages/MediaDetailPage.vue`
- Frontend: `frontend/src/stores/remoteControl.js`

Umsetzung:

1. Status-Polling fuer native Cast-Ziele verbessern.
   - Bestehende Target-Commands und Statusmethoden in `cast.py` erweitern.
   - Ergebnis in `RemoteControlButton.vue` sichtbar machen.
   - Bestehende Target-Struktur beibehalten.

2. Queue-Load und Media-Status robuster machen.
   - Bei Cast-Zielen aktive Media-Session-ID aufloesen und cachen.
   - Nach `play`, `pause`, `resume`, `seek`, `stop`, `volume`, `mute`
     Status neu laden.

3. DLNA/AirPlay Metadaten weiter anreichern.
   - MIME, Artwork, Titel, Creator, Duration und Startposition aus bestehenden
     Playback-Infos ableiten.
   - Keine fremden Controller-Pfade einfuehren.

Tests:

```bash
cd /root/pyrate.media/backend
python3 -m py_compile src/pyrate/api/v1/cast.py
python3 -m pytest tests/api/test_cast_api.py -q

cd /root/pyrate.media/frontend
npm test -- --run test/vitest/stores/remoteControl.store.spec.js
```

## 4. Provider-Tiefe fuer Untertitel, Lyrics und Artwork

Prioritaet: mittel bis hoch, weil es reale Library-Korrektur-Workflows betrifft.

Bestehende Owner:

- Untertitel API: `backend/src/pyrate/api/v1/subtitles.py`
- Untertitel Service: `backend/src/pyrate/services/subtitle_provider.py`
- Lyrics API: `backend/src/pyrate/api/v1/lyrics.py`
- Metadata API: `backend/src/pyrate/api/v1/metadata.py`
- Media API: `backend/src/pyrate/api/v1/media.py`
- Frontend Detailseite: `frontend/src/pages/MediaDetailPage.vue`
- Frontend Medien-Dateien/Tracks: vorhandene Media-Komponenten erweitern

Umsetzung:

1. Untertitelprovider erweitern.
   - Bestehende Provider-Normalisierung und Scoring nutzen.
   - Match-Reasons im UI sichtbar machen.
   - Download-Ergebnis direkt als verwalteten Subtitle am Media-Item ablegen.

2. Lyrics-Provider vertiefen.
   - Bestehende Remote-Search/Download-Flows erweitern.
   - Synchronisierte Lyrics und Plaintext sauber unterscheiden.
   - Audio-Player-Anzeige pruefen.

3. Artwork-Workflows abrunden.
   - Remote-Image-Suche mit Sprache, Typ und Provider-Feldern besser filtern.
   - Upload/Remote-Select sollen gleiche Transform-Pipeline nutzen.
   - Kein neuer Artwork-Service, wenn `media.py`/`metadata.py` reicht.

Tests:

```bash
cd /root/pyrate.media/backend
python3 -m py_compile \
  src/pyrate/api/v1/subtitles.py \
  src/pyrate/services/subtitle_provider.py \
  src/pyrate/api/v1/lyrics.py \
  src/pyrate/api/v1/metadata.py \
  src/pyrate/api/v1/media.py
python3 -m pytest tests/api/test_subtitles_api.py tests/api/test_lyrics_api.py tests/api/test_metadata_api.py tests/api/test_media_api.py -q
```

## 5. Admin-Observability, Tasks, Backup und Activity abrunden

Prioritaet: mittel.

Bestehende Owner:

- `backend/src/pyrate/api/v1/activity_logs.py`
- `backend/src/pyrate/services/activity_log.py`
- `backend/src/pyrate/api/v1/notifications.py`
- `backend/src/pyrate/services/notification.py`
- `backend/src/pyrate/api/v1/backups.py`
- `backend/src/pyrate/api/v1/tasks.py`
- `backend/src/pyrate/services/task_events.py`
- Frontend Admin-Seiten: Logs, Tasks, Settings, Devices, Sessions

Umsetzung:

1. Activity-Events ausbauen.
   - Session-Commands, Cast-Commands, Backup/Restore, Task-Starts,
     Settings-Aenderungen und Provider-Downloads konsistent loggen.
   - Bestehenden `ActivityLogService` nutzen.

2. Admin-Logs besser filterbar machen.
   - Frontend Logs-Seite um Event-Type, Severity, Entity-Type und Datum
     erweitern, wenn Backend das bereits liefert.
   - Wenn Backend fehlt, `activity_logs.py` erweitern.

3. Backup/Restore UI robuster machen.
   - Dry-run fuer Restore prominent anzeigen.
   - Destruktive Optionen nur nach expliziter Bestaetigung.
   - Bestehende `backups.py` Endpoints nutzen.

4. Task-Run Details anzeigen.
   - Bestehende Task-History/Run-Status aus `tasks.py` und
     `task_events.py` in `TasksPage` sichtbar machen.

Tests:

```bash
cd /root/pyrate.media/backend
python3 -m py_compile \
  src/pyrate/api/v1/activity_logs.py \
  src/pyrate/services/activity_log.py \
  src/pyrate/api/v1/backups.py \
  src/pyrate/api/v1/tasks.py \
  src/pyrate/services/task_events.py
python3 -m pytest tests/api/test_activity_logs_api.py tests/api/test_backups_api.py tests/api/test_tasks_api.py -q
```

## 6. Search/Filter UX nachziehen

Prioritaet: mittel. Backend und Payload sind weitgehend vorhanden.

Bestehende Owner:

- Backend: `backend/src/pyrate/api/v1/search.py`
- Backend: `backend/src/pyrate/services/search.py`
- Backend: `backend/src/pyrate/api/v1/filters.py`
- Backend: `backend/src/pyrate/services/library.py`
- Frontend: `frontend/src/components/SearchFilterBar.vue`
- Frontend: `frontend/src/composables/useSearchFilters.js`
- Frontend: `frontend/src/composables/useSearchAPI.js`
- Frontend: `frontend/src/pages/SearchResultsPage.vue`
- Frontend: `frontend/src/utils/searchOptions.js`

Umsetzung:

1. Advanced-Filter visuell gruppieren.
   - Basisfilter sichtbar lassen.
   - Ausschlussfilter in einklappbaren Advanced-Bereich verschieben.
   - Keine neue Suchseite.

2. Active Filter Chips ergaenzen.
   - Chips aus URL-State ableiten.
   - Einzelne Filter per Chip entfernen.
   - "Clear all" nutzt bestehende Filter-State-Logik.

3. Person-/Year-Filter besser navigierbar machen.
   - Typed Autocomplete und Filterbar auf gleiche Query-Keys ausrichten.
   - Keine separaten Person-/Year-Controller anlegen.

Tests:

```bash
cd /root/pyrate.media/frontend
npx eslint src/components/SearchFilterBar.vue src/composables/useSearchFilters.js src/composables/useSearchAPI.js src/pages/SearchResultsPage.vue src/utils/searchOptions.js
npm test -- --run test/vitest/composables/useSearchFilters.spec.js test/vitest/composables/useSearchAPI.spec.js test/vitest/composables/useTypedAutocomplete.spec.js
```

## 7. Offline- und Device-Sync weiter ausbauen

Prioritaet: mittel.

Bestehende Owner:

- Backend: `backend/src/pyrate/api/v1/devices.py`
- Frontend: `frontend/src/stores/offline.js`
- Frontend: `frontend/src/pages/PlayPage.vue`
- Frontend: `frontend/src/components/user-settings/DevicesSection.vue`

Umsetzung:

1. Offline-Manifest UI sichtbar machen.
   - Pro Device anzeigen: queued, downloading, ready, failed, removed.
   - Bestehende `/api/devices/{device_guid}/offline-items` und
     `/manifest` Endpoints nutzen.

2. Offline-Playback robuster machen.
   - Blob-URL Lifecycle in `PlayPage.vue` pruefen.
   - Subtitle-Blob-URLs sauber revoken.
   - Ablaufdatum und Fehlerstatus im Store abbilden.

3. Permission/Limit-Hinweise anzeigen.
   - Wenn Backend Offline-Anfrage ablehnt, konkrete Meldung im UI.

Tests:

```bash
cd /root/pyrate.media/frontend
npm test -- --run test/vitest/stores/offline.store.spec.js

cd /root/pyrate.media/backend
python3 -m pytest tests/api/test_devices_api.py -q
```

## 8. Plugin- und Runtime-Scope klaeren

Prioritaet: mittel, aber sicherheitskritisch.

Bestehende Owner:

- Backend: `backend/src/pyrate/api/v1/plugins.py`
- Backend: `backend/src/pyrate/api/v1/notifications.py`
- Frontend: `frontend/src/pages/admin/PackagesPage.vue`
- Frontend: `frontend/src/pages/admin/EditPackagePage.vue`

Umsetzung:

1. Nur Metadaten und validierte Capabilities ausbauen.
   - Kein beliebiges Package ausfuehren.
   - Runtime-Felder duerfen angezeigt und validiert werden.
   - Echte Ausfuehrung erst nach separatem Sandbox-/Runtime-Design.

2. Plugin-advertised notification events validieren.
   - Bestehenden Event-Katalog nutzen.
   - Invalid Events im Admin-UI sichtbar machen.

3. Repository-Sync UI verbessern.
   - Installed/available/update state anzeigen.
   - Keine fremden Package-Controller-Namen uebernehmen.

Tests:

```bash
cd /root/pyrate.media/backend
python3 -m py_compile src/pyrate/api/v1/plugins.py src/pyrate/api/v1/notifications.py
python3 -m pytest tests/api/test_plugins_api.py tests/api/test_notifications_api.py -q
```

## Nicht jetzt starten ohne Rueckfrage

- Live-TV, DVR, Channels oder Recording als neue Domaene.
  - Dafuer ist eine Produktentscheidung noetig.
  - Falls gewuenscht, zuerst Owner-Suche dokumentieren.
  - Falls kein Owner existiert, native pyrate Domaene entwerfen, nicht fremde
    Routen kopieren.

- Neue Install-/Startup-Routefamilien.
  - Setup bleibt in `backend/src/pyrate/api/v1/install.py`.
  - Keine startup-benannten Install-Routen.

- Neue Playlist-/Collection-Systeme.
  - Listen, Collections und Playlists gehoeren weiter in `lists.py` und
    `ListService`.

## Abschlussformat fuer den naechsten Agenten

Nach jedem Block:

1. Kurz schreiben, welcher bestehende Owner erweitert wurde.
2. Commit pro Repo direkt auf `main`, wenn der User das so will.
3. Verifikation nennen:
   - Lint/Test/Compile.
   - Wenn `pytest` fehlt, exakt melden.
   - Audit-Ergebnis nennen.
4. Keine Merge- oder MR-Links erfinden, wenn direkt auf `main` gepusht wurde.
