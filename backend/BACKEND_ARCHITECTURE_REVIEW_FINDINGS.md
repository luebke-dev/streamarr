# Backend Architecture Review Findings

Stand: 2026-05-11

Scope: statischer Review von `backend/src/pyrate` und `backend/tests` mit Fokus auf Antipatterns, Sicherheitsrisiken, Duplizierung, Modulgrenzen und Testqualität. Es wurden keine Backend-Codefixes vorgenommen.

## Kurzfazit

Das Backend hat eine solide Service-/Router-Grundstruktur, aber mehrere zentrale Flows sind inzwischen zu groß und zu breit geworden. Die wichtigsten Risiken liegen bei verstreuter Media-Access-Logik, uneinheitlich geschützten mutierenden Endpoints, Businesslogik in FastAPI-Routern und nicht eindeutigen Transaktionsgrenzen zwischen API und Services.

## Empfohlene Reihenfolge

1. Zentrale Media-Access-Policy einführen und fehlende Checks schließen.
2. Mutierende Media-/Library-Import-Endpunkte auf klares RBAC-Modell bringen.
3. Transaktionsgrenzen normalisieren, bevor große Import-/Playback-Flows weiter refactored werden.
4. Große Router/Services entlang fachlicher Grenzen zerlegen.
5. Tests von Coverage-Mocks zu Permission-/Transaction-/Integration-Cases verschieben.

## Findings

### HIGH: Media-Access-Policy ist verstreut und an einigen Endpoints unvollständig

**Problem**

Library-Permissions, Superuser-Ausnahmen und Parental-Control-Checks werden pro Endpoint manuell umgesetzt. Dadurch driften die Regeln auseinander. Einige medienbezogene Endpoints liefern oder verändern Media-Status ohne `UserPermissionsDep` oder Age-Gate.

**Belege**

- `src/pyrate/api/v1/search.py:171-201`: `/search/local` nutzt nur `CurrentUser` und ruft `elasticsearch_service` direkt auf. Keine `UserPermissionsDep`, keine `allowed_libraries`, kein `parental_max_age`.
- `src/pyrate/api/v1/genres.py:22-69` und `src/pyrate/api/v1/genres.py:89-134`: Genre-Endpunkte geben `MediaItemSummary` zurück, filtern aber nur global deaktivierte Media-Typen, nicht Nutzerrechte oder Altersfreigaben.
- `src/pyrate/api/v1/media.py:2809-2866`: Availability und Watch-Toggle prüfen nur, ob das `MediaItem` existiert. Kein Library-/Age-Check.
- `src/pyrate/api/v1/lightrays.py:54-83`: Game-Launch prüft `MediaType.GAMES` und `max_game_streams`, aber nicht explizit `games` in `allowed_libraries` oder Parental-Control.
- Das Muster existiert mehrfach: direkte `MEDIA_TYPE_TO_LIBRARY`-/`allowed_libraries`-Checks sind über viele Router verteilt.

**Ziel**

Eine zentrale Policy-Schicht einführen, z. B. `MediaAccessService` oder FastAPI-Dependencies:

- `can_read_media(user, permissions, media_item)`
- `can_play_media(user, permissions, media_item)`
- `can_mutate_media(user, media_item)`
- `can_request_offline(user, permissions, media_item)`

**Acceptance Criteria**

- Alle Endpoints, die Media-Items oder Media-Summaries zurückgeben, verwenden dieselbe Read-Policy.
- Alle Playback-/Download-/Offline-/Watch-/Availability-Flows verwenden dieselbe Media-Zugriffsprüfung.
- Tests decken mindestens `/search/local`, Genres, Availability, Watch, Lightrays und reguläre `/media`-Reads für non-admin, admin, gesperrte Library und Parental-Control ab.

### HIGH: Mutierende Media-/Library-Import-Endpunkte sind nur mit `CurrentUser` geschützt

**Problem**

Mehrere Endpunkte verändern globale Media-/Library-Daten, verwenden aber nur `CurrentUser`. In derselben Datei sind viele administrative Endpoints bereits mit `get_current_superuser` geschützt. Das wirkt inkonsistent und ist wahrscheinlich zu breit.

**Belege**

- `src/pyrate/api/v1/media.py:1292-1324`: `create_media_item` erstellt globale Media-Items mit `CurrentUser`.
- `src/pyrate/api/v1/media.py:1618-1644`: `update_media_item` patcht globale Media-Items mit `CurrentUser`.
- `src/pyrate/api/v1/libraries.py:1950-1955`: `import_trending_items` importiert Provider-Daten und aktualisiert Systemlisten, aber nutzt `Depends(get_current_user)`.
- `src/pyrate/api/v1/libraries.py:2412-2420`: `import_by_external_id` erstellt globale Media-Items, Seasons und Episodes mit `Depends(get_current_user)`.
- `src/pyrate/api/v1/libraries.py:492`, `547`, `631`, `902+`: viele benachbarte Library-Admin-Endpunkte nutzen `get_current_superuser`.

**Ziel**

Ein klares RBAC-Modell für mutierende Media-Aktionen definieren:

- Admin-only für globale Library-/Media-Verwaltung.
- Optional separater User-Request-Flow für normale Nutzer, der keine globalen Daten direkt mutiert oder über eine Queue/Approval läuft.

**Acceptance Criteria**

- Non-admins können keine globalen Media-Items erstellen, patchen oder globale Importläufe starten, außer es gibt eine explizite Permission dafür.
- Tests prüfen 403 für normale Nutzer und Erfolg für Admins.
- Falsche Typannotation `current_user: dict` wird durch `User`/`CurrentUser` ersetzt.

### HIGH: Transaktionsgrenzen sind uneinheitlich und Services committen intern

**Problem**

Viele Services committen selbst. Gleichzeitig committen Router und Worker ebenfalls. Dadurch sind zusammengesetzte Workflows schwer atomar zu halten. Besonders Import-Flows wirken transaktional, sind es aber nur teilweise, weil aufgerufene Services bereits committen.

**Belege**

- `src/pyrate/services/media.py:81-92`: `_persist` committed jedes Entity direkt.
- `src/pyrate/services/media.py:525-526`, `561`, `577`, `592`, `605`: Update/Delete-Methoden committen intern.
- `src/pyrate/services/list.py:249-283`, `285-305`, `720-738`, `1068-1107`: Listenoperationen committen intern.
- `src/pyrate/services/activity_log.py:23-33`: Activity-Log schreibt und committed selbst.
- `src/pyrate/api/v1/media.py:1588-1612` und `1647-1684`: Endpoint committed Media-Änderung und ruft danach einen Service auf, der erneut committed.
- `src/pyrate/api/v1/libraries.py:2160-2321`: `import_trending_items` nutzt `db.begin_nested()`, ruft aber Services auf, die intern committen.

**Ziel**

Eine Unit-of-Work-Konvention festlegen:

- Entweder API/Worker besitzen die Transaktion und Services machen nur `add`/`flush`.
- Oder Services sind explizit transaction-owning, aber dann dürfen API-Flows keine Schein-Atomizität mit `begin_nested()` suggerieren.

**Acceptance Criteria**

- Neue Service-Methoden committen nicht mehr implizit, außer der Methodenname dokumentiert es klar.
- Import- und Metadata-Update-Flows sind entweder vollständig atomar oder bewusst in idempotente Teilschritte zerlegt.
- Tests simulieren Fehler nach Media-Erstellung, nach External-ID-Erstellung und nach Activity-Log und prüfen den erwarteten DB-Zustand.

### MEDIUM: Große Router enthalten Businesslogik statt dünner HTTP-Schicht

**Problem**

Mehrere API-Dateien sind God-Router geworden. Sie enthalten Pydantic-Modelle, Provider-Auswahl, Importlogik, Serialisierung, Permission-Checks, Transcoding-Entscheidungen und DB-Operationen in einer Datei.

**Belege**

- `src/pyrate/api/v1/media.py`: 3719 Zeilen, 51 Route-Handler.
- `src/pyrate/api/v1/libraries.py`: 2934 Zeilen, 39 Route-Handler.
- `src/pyrate/api/v1/play.py`: 1866 Zeilen.
- `src/pyrate/api/v1/libraries.py:1950-2389`: `import_trending_items` ist ca. 439 Zeilen und enthält Provider-Setup, Mapping, Media-Erstellung, External IDs, Seasons/Episodes, Liste-Sync und Fehlerbehandlung.
- `src/pyrate/api/v1/play.py:773-1444`: `play_media` ist ca. 672 Zeilen und orchestriert Permission, Source-Auswahl, Codec-Verhandlung, Rate-Limits, Container-Handling, Token und Response.
- `src/pyrate/api/v1/media.py:968-1289`: `list_media_items` ist ca. 321 Zeilen mit sehr vielen Query-Parametern und doppeltem `list_media_items`/`count_media_items`-Parameterblock.

**Ziel**

Router in fachliche Module und Service-Orchestratoren schneiden:

- `media_read.py`, `media_admin.py`, `media_files.py`, `media_releases.py`, `media_artwork.py`
- `library_paths.py`, `library_imports.py`, `library_scoring.py`
- `PlaybackDecisionService`, `PlaybackSessionService`

**Acceptance Criteria**

- Route-Handler bleiben unter ca. 80 Zeilen und enthalten primär HTTP-Parsing, Policy-Aufruf und Service-Aufruf.
- Import-/Playback-Entscheidungen sind direkt unit-testbar ohne FastAPI-Testclient.
- Request-Filter werden als Pydantic-Filterobjekte oder Dependency-Objekte gebündelt.

### MEDIUM: Playback-Logik ist dupliziert und leakt Infrastrukturdetails in den Router

**Problem**

`get_playback_info` und `play_media` berechnen ähnliche Capability-, Codec-, Quality- und Playback-Method-Entscheidungen getrennt. Zusätzlich greift `play_media` direkt auf Docker zu, obwohl es mit `ComputingService` bereits eine Provider-Abstraktion gibt.

**Belege**

- `src/pyrate/api/v1/play.py:452-590`: `get_playback_info` resolved Capabilities, Quality, Transcoding-Settings und Direct-Play/Stream/Transcode-Entscheidung.
- `src/pyrate/api/v1/play.py:773-1444`: `play_media` wiederholt große Teile davon und startet zusätzlich Sessions.
- `src/pyrate/api/v1/play.py:1334-1348`: direkter synchroner `import docker`, `docker.from_env()`, Container-List/Stop/Remove im async Route-Handler.
- `src/pyrate/services/computing.py:235-301`: es existiert bereits eine async Provider-Abstraktion für Docker/Kubernetes.

**Ziel**

Playback in zwei Schichten teilen:

- `PlaybackDecisionService`: reine Entscheidung über Source, Method, Codecs, Direct-Play/Stream/Transcode.
- `TranscodeLifecycleService`: Token, Locks, Session, Container-Cleanup, Start.

**Acceptance Criteria**

- `get_playback_info` und `play_media` nutzen dieselbe Decision-Funktion.
- Kein direkter Docker-SDK-Zugriff mehr in API-Routern.
- Docker/Kubernetes-Handling läuft ausschließlich über `ComputingService` oder eine dedizierte Lifecycle-Abstraktion.

### MEDIUM: Manuelle Serialisierung und Mapping-Code duplizieren Schemas

**Problem**

Einige Endpoints bauen Response-Dicts händisch aus ORM-Objekten. Das macht Feldlisten fehleranfällig, führt zu driftenden Response-Formaten und erschwert Tests.

**Belege**

- `src/pyrate/api/v1/media.py:1399-1515`: `get_media_item` baut `item_dict` manuell mit Files, Releases, Links, External IDs und Cast.
- `src/pyrate/api/v1/media.py:1117-1270`: `list_media_items` übergibt denselben großen Filterblock an `list_media_items` und `count_media_items`.
- `src/pyrate/api/v1/search.py:66-121`: Filter-Erkennung wird manuell aus vielen optionalen Feldern zusammengesetzt.

**Ziel**

Mapper und Filterobjekte einführen:

- `MediaItemSerializer` oder Schema-Factory für Detailresponses.
- `MediaFilterParams` als Dependency/Pydantic-Modell.
- Ein Service-Call, der Items und Count aus demselben Filterobjekt erzeugt.

**Acceptance Criteria**

- Keine langen handgeschriebenen ORM-zu-dict-Listen in Routern.
- Neue Felder müssen nur an einer Stelle für Read/List/Search gemappt werden.
- List/Count verwenden dasselbe Filterobjekt.

### MEDIUM: Search-Service mischt Provider-Suche, Import-Queue und lokale Suche

**Problem**

Search ist nicht nur Suche. Provider-Ergebnisse werden gefiltert, Imports werden queued oder synchron erstellt, lokale Elasticsearch-Fallbacks laufen im selben Service, und Provider-spezifische Importlogik liegt ebenfalls dort. Das erhöht Seiteneffekte und macht Permission-Tests schwer.

**Belege**

- `src/pyrate/services/search.py:565-605`: Provider-first Search fällt bei beliebiger Exception auf lokale Suche zurück und queued optional Imports.
- `src/pyrate/services/search.py:1510-1730`: derselbe Service enthält konkrete TMDB-/IGDB-/Spotify-Importhelpers und commit-relevante Logik.
- `src/pyrate/services/elasticsearch.py:429-480`, `628-680`, `990-1045`: Elasticsearch Query-Aufbau für Movies, Shows und All ist stark ähnlich.

**Ziel**

Search in klare Verantwortlichkeiten trennen:

- `ProviderSearchService`
- `LocalSearchService`
- `SearchImportQueueService`
- gemeinsamer Elasticsearch-Query-Builder

**Acceptance Criteria**

- Eine reine Suche kann ohne Import-Seiteneffekte laufen.
- Provider-Failures und Programmierfehler werden unterschiedlich behandelt.
- Elasticsearch Query-Definitionen sind zentral und werden nicht pro Medientyp kopiert.

### MEDIUM: Library-Plugins duplizieren Video-/Filesystem-Logik

**Problem**

Movie- und Show-Plugins enthalten viel ähnliche Logik für Pfadvalidierung, Statistik, Extension-Sets, Scans, Release-Metadata, Scoring und Promote-to-Library. Gleichzeitig sind Sicherheitschecks nicht gleich stark.

**Belege**

- `src/pyrate/libraries/movies.py:30-91` und `src/pyrate/libraries/shows.py:37-101`: sehr ähnliche `validate_path`, Stats und Video-Extension-Logik.
- `src/pyrate/libraries/movies.py:230-259` und `src/pyrate/libraries/shows.py:240-275`: ähnliche Media-File-Validation.
- `src/pyrate/libraries/movies.py:370-455` und `src/pyrate/libraries/shows.py:385-475`: ähnliche Release-Scoring-Blöcke mit leicht anderer Gewichtung.
- `src/pyrate/libraries/movies.py:1004-1065`: Movie-Promotion resolved Zielpfade und prüft `is_relative_to(library_root)`.
- `src/pyrate/libraries/shows.py:1051-1116`: Show-Promotion baut Zielpfade per String und hat keinen expliziten `resolve()`/`is_relative_to()`-Check wie Movies.

**Ziel**

`VideoLibraryBase` oder Helper-Modul einführen:

- gemeinsame Extension-Sets und Scan-/Stats-Helfer
- gemeinsame Path-Safety-Funktion
- parametrisierte Release-Scoring-Weights
- Promote-to-Library-Template mit identischer Root-Validation

**Acceptance Criteria**

- Movie/Show enthalten nur noch medientypspezifische Parsing- und Naming-Regeln.
- Alle Promote-Flows validieren Zielpfade identisch.
- Blocking File-Kopien und tiefe Scans laufen nicht direkt im Request-Eventloop.

### MEDIUM: Worker ist ein God-Modul mit vielen Aufgaben und breiter Fehlerbehandlung

**Problem**

`worker.py` enthält Scheduling, Download-Refresh, Imports, Notifications, Metadata, Search, Cleanup, Recommendations und Transcode-Monitoring in einem Modul. Das erschwert Ownership, Tests und gezielte Deploy-/Retry-Entscheidungen.

**Belege**

- `src/pyrate/worker.py`: 1681 Zeilen, 37 `@broker.task`-Definitionen.
- `src/pyrate/worker.py`: 46 Vorkommen von `except Exception`.
- `src/pyrate/worker.py:98-130`: Scheduled Download-Polling mit internem Minutenloop.
- `src/pyrate/worker.py:430-447`, `589-647`: mehrere Trending-Import-Schedules mit ähnlicher Struktur.
- `src/pyrate/worker.py:1092-1424`: mehrere Cleanup- und Monitor-Aufgaben im selben Modul.

**Ziel**

Worker in Pakete splitten:

- `workers/downloads.py`
- `workers/imports.py`
- `workers/metadata.py`
- `workers/playback.py`
- `workers/cleanup.py`
- `workers/recommendations.py`

**Acceptance Criteria**

- Broker-Definition bleibt zentral, Task-Funktionen liegen fachlich getrennt.
- Gemeinsamer Error-/Retry-Decorator reduziert wiederkehrendes `try/except Exception`.
- Tests können einzelne Worker-Domains importieren, ohne alle Task-Abhängigkeiten zu laden.

### MEDIUM: Broad exception handling versteckt Fehlerklassen

**Problem**

Viele Flows fangen `Exception`, loggen und machen weiter oder fallen auf einen anderen Pfad zurück. Das ist für Provider-Ausfälle sinnvoll, verdeckt aber Programmierfehler, Dateninkonsistenzen und Security-Probleme.

**Belege**

- `src/pyrate/services/search.py:597-605`: beliebige Exception in Provider-Suche führt zu lokalem Fallback.
- `src/pyrate/api/rate_limit.py:75-81`: Rate-Limiter fail-open bei jeder Redis-Exception.
- `src/pyrate/api/v1/libraries.py:2317-2319`: einzelne Importfehler werden geschluckt und der Import läuft weiter.
- `src/pyrate/api/v1/play.py:1316-1319`: Fehler beim Concurrent-Stream-Check werden nur debug-geloggt.

**Ziel**

Exception-Taxonomie einführen:

- erwartete externe Fehler: ProviderUnavailable, RateLimitUnavailable, RedisUnavailable
- erwartete Datenfehler: NotFound, InvalidMetadata
- unerwartete Bugs: mit `exc_info=True` loggen und fail closed, wo Security/Limit betroffen ist

**Acceptance Criteria**

- Security-/Limit-Checks fallen nicht stillschweigend weg.
- Provider-Fallbacks fangen nur bekannte Provider-/Transportfehler.
- Logs enthalten genug Kontext, ohne sensitive Daten auszugeben.

### LOW: Viele lokale Imports deuten auf zyklische Abhängigkeiten und schwache Modulgrenzen

**Problem**

Viele Router importieren Services und Models innerhalb von Funktionen. Das ist manchmal legitim, wirkt hier aber als Symptom für zu breite Module und Abhängigkeitszyklen.

**Belege**

Gezählte lokale Imports in API-Funktionen:

- `src/pyrate/api/v1/media.py`: 34
- `src/pyrate/api/v1/libraries.py`: 24
- `src/pyrate/api/v1/play.py`: 22
- `src/pyrate/api/v1/tasks.py`: 20

**Ziel**

Durch Modul-Splits und Service-Orchestratoren die Abhängigkeiten entkoppeln, sodass Imports wieder überwiegend am Modulanfang stehen können.

**Acceptance Criteria**

- Lokale Imports bleiben nur für optionale Dependencies oder bewusst verzögerte schwere Imports.
- Keine lokalen Imports mehr, die nur existieren, um Router/Service-Zyklen zu umgehen.

### LOW: Test-Suite enthält Coverage-orientierte Großtests statt fokussierter Verhaltensspezifikation

**Problem**

Ein Teil der Tests wirkt explizit darauf optimiert, Zeilenabdeckung zu erhöhen. Große Mock-heavy Tests sind nützlich für Regressionen, können aber echte Integrations- und Policy-Fehler übersehen.

**Belege**

- `tests/test_worker_coverage.py:1-7`: Docstring sagt explizit "increase coverage" und "happy path to maximize line coverage"; Datei hat 5429 Zeilen.
- `tests/test_remaining_coverage.py:1-21`: sammelt viele Themen in einer Datei.
- Sehr viele `MagicMock`-/`AsyncMock`-/`patch`-basierte Tests, besonders Worker/Playback/Download.

**Ziel**

Coverage-Tests schrittweise in verhaltensorientierte Tests umbauen:

- Permission/Parental-Control Contract Tests für alle medienbezogenen Endpoints.
- Transaction-Rollback-Tests für Import- und Metadata-Flows.
- Worker-Tests pro Domain mit realistischeren Service-Fakes statt tiefer Monkeypatch-Ketten.

**Acceptance Criteria**

- Neue Security-/Transaction-Fixes werden durch Integrationstests auf API- oder Serviceebene abgesichert.
- Große Coverage-Dateien werden in fachliche Testdateien zerlegt.
- Mock-Tests prüfen nicht nur Call-Counts, sondern beobachtbares Verhalten und Persistenzzustand.

## Tooling-Hinweise

- `python3 -m ruff check src/pyrate` konnte in dieser lokalen Umgebung nicht laufen: `No module named ruff`.
- `python3 -m mypy src/pyrate --no-error-summary` konnte in dieser lokalen Umgebung nicht laufen: `No module named mypy`.
- Die statischen Findings basieren auf Dateimetriken, AST-Metriken, Greps und gezieltem Lesen der betroffenen Module.
