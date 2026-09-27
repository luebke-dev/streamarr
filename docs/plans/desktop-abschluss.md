# Abschluss der Desktop-App (Phasen 2–5)

**Stand:** alle sieben Arbeitspakete abgeschlossen · 51 Commits auf `feat/desktop-app`
**Nicht gepusht, nicht ausgeliefert, kein Servereingriff.**

Diese Seite liest die zehn Erfolgskriterien Punkt für Punkt gegen und trennt
scharf zwischen *gemessen* und *offen*. Sie ist die ehrliche Gegenseite zu
„alles grün": die Testzahlen sind belegt, die Live-Nachweise fehlen an drei
Stellen, und das hat einen einzigen Grund.

## Der eine Grund für alle Lücken

Der Testserver dieser Installation hat **keine Datenbank** mehr. Der Container
`app-db-1` wurde zerstört, und ein verwaister Docker-Netzwerk-Endpunkt hält die
Adresse, die das Backend braucht. Die Daten selbst sind intakt (1,6 GB), die
Reparatur ist zwei Befehle lang — und sie erfordert einen **Docker-Daemon-
Neustart**, den der Auftraggeber ausdrücklich abgelehnt hat.

Vollständig dokumentiert in [`desktop-testserver-stand.md`](desktop-testserver-stand.md),
inklusive Durchstichprüfung für danach.

Deshalb sind genau drei Dinge offen, die eine Live-Verbindung brauchen: **Login,
Medienwiedergabe und Spiel-Streaming gegen den echten Server.**

## Die zehn Kriterien

| # | Kriterium | Stand |
|---|---|---|
| 1 | Medien über den nativen mpv-Kern | **gebaut**, live offen |
| 2 | HDR10 durchgereicht oder nachweisbar gemappt | **gemessen** |
| 3 | Spiele über GStreamer/WebRTC nativ | **gebaut und verdrahtet**, live offen |
| 4 | Couch-/Big-Picture-Modus in der UI | **gebaut**, ohne Controller |
| 5 | Alle Rust-Crates grün | **gemessen** |
| 6 | Frontend ohne neue Fehler | **gemessen** |
| 7 | Golden-Tests des Wire-Vertrags | **gemessen** |
| 8 | Installierbare Pakete, Linux und Windows | **Linux gemessen**, Windows in CI |
| 9 | Doku und CI | **gemessen** |
| 10 | Server-Zwischenstand festgehalten | **gemessen** |

## Was gemessen ist

**Rust.** `desktop/player` 514 Tests feature-frei und mit `mpv`/`spike`, 537 mit
`gamepad`. `frontend/src-tauri` 143 Tests ohne und 145 mit `gamestream`.
`cargo fmt --all --check` und `clippy --locked --all-targets -- -D warnings`
sauber in **allen sechs** Konfigurationen.

**Frontend.** 405 Tests grün, 24 Fehler in 9 Dateien — genau die dokumentierte
Baseline, unverändert über die gesamte Arbeit. ESLint sauber, `npx quasar build`
erfolgreich.

**Pakete.** `.deb` (10,8 MB), `.rpm` (10,8 MB) und AppImage (120 MB) gebaut und
geöffnet. Jede direkt gelinkte Bibliothek ist deklariert, geprüft von
`desktop/scripts/check_bundle_deps.sh` — das Skript hat dabei **acht** fehlende
Abhängigkeiten gefunden, darunter `libudev1` (durch die eigene
Controller-Unterstützung) und drei GStreamer-Pakete (durch die Spiel-Verdrahtung).

**Die App läuft.** Live gestartet und am Prozess belegt: ein Wayland-Fenster
(`wayland-cursor`-Deskriptor), GPU-Zugriff (`/dev/dri/renderD128`, dreifach
geöffnet), 60 Threads, 177 MB, darunter `gilrs` (der Controller-Leser) und
`VBlankMonitor` (echtes Rendering, kein Null-Backend).

**HDR.** Der EDID/CTA-861-Parser liest den echten Monitor und erkennt ihn als
HDR10-fähig, deckungsgleich mit `edid-decode`. Der Live-Test fand dabei einen
Fehler in meinen eigenen Unit-Tests: PQ ist **Bit 2**, nicht Bit 1.

**Die Spiel-Pipeline.** `DECODED=10`, `INPUT_SENT=6 INPUT_RECEIVED=6` über einen
echten WebRTC-Datenkanal, reproduzierbar. Die `mouseabs`-Zeile zeigt die
Letterbox-Korrektur in Aktion: aus einem Punkt in der Flächenmitte wird
`x=640, y=360` — die Mitte des *Bildes*.

## Was offen ist, und warum

**Drei Live-Nachweise** (Login, Medien, Spiele gegen den Server): die Datenbank
fehlt, siehe oben. Die Kette ist jeweils gegen einen Ersatzserver mit echten
Medien, echtem Profil und echtem Tunnel belegt — das ist **nicht** dasselbe.

**Ein Spiel auf dem Bildschirm.** Die Client-Pipeline ist bewiesen und in die App
verdrahtet, aber der Beweis ist Schleife-zu-Schleife. Ob App und Lightrays
miteinander können, ist ungemessen.

**Ein Support-Bericht, der ankommt.** `POST /api/client-logs` ist ohne Datenbank
nicht erreichbar. Die Logik und der Dialog sind getestet, der Rundlauf nicht.

**Couch-Modus mit einem echten Controller.** Auf dieser Maschine gibt es kein
Gamepad. Die Geometrie, die Wiederholregel und die Shell-Befehle sind getestet,
der Tastaturweg durchgängig — der Controller-Weg ist nie von einem Menschen
gedrückt worden.

**Windows.** NSIS und MSI werden in der CI auf `windows-latest` gebaut, und der
Job prüft, dass beide Artefakte existieren. Aber **kein Mensch** hat einen dieser
Installer ausgeführt. Es gibt in diesem Projekt keinen Windows-Host.

**OIDC-Login.** Der Testserver hat `oidc_enabled: false`.

**AppImage-*Einhängen*.** FUSE funktioniert im Baucontainer nicht. Der
*entpackte* AppImage läuft nachweislich (über `AppRun`); das direkte Starten von
`usr/bin/Streamarr` scheitert erwartungsgemäß, weil `AppRun` die WebKit-Pfade
setzt.

**Ein Update, das installiert wurde.** Es gibt kein Release.

**macOS.** Außerhalb des Umfangs.

## Was diese Arbeit über sich selbst gelernt hat

Die Fehler, die zählten, kamen nicht aus dem Nachdenken, sondern aus dem Messen:

* Ein **leerer STUN-Server ist nicht kein STUN-Server**. Der Unterschied war
  `ENCODED=1, DECODED=0` gegen einen laufenden Stream.
* **Falsche GLib-Typen** (`i32` statt `guint`) bringen den Prozess in GLib zum
  Absturz, statt einen Fehler zurückzugeben.
* **`watch` ohne `immediate`** feuert nie — der Report-Dialog zeigte eine leere
  Liste, und nichts am Code sah falsch aus.
* Die **Pakete enthielten die Spiel-Verdrahtung nicht**, weil `tauri build` die
  Standard-Features nutzt. Jeder Test war grün, weil jeder Test gegen einen Build
  *mit* dem Feature lief.
* **`mkdocs --strict` prüft keine Anker derselben Seite.** Ein Skript von mir
  löschte einen ganzen Abschnitt, und `--strict` schwieg.
* **`valid_up_to()` ist 0**, wenn ein Schnitt mitten in einem Zeichen liegt — mein
  erster Reparaturversuch war falsch, und nur der Test zeigte es.

Drei davon — die fehlenden Paketabhängigkeiten, das fehlende Feature im Paket und
der gelöschte Abschnitt — hätten ausgeliefert werden können, ohne dass ein Test
angeschlagen hätte. Gefunden wurden sie durch Prüfskripte, die aus genau diesen
Fehlern entstanden sind.

## Was vor einer Auslieferung noch fehlte

1. Den Server instand setzen (`desktop-testserver-stand.md`) und die drei
   Live-Nachweise nachholen.
2. Einen Windows-Installer von Hand installieren und starten.
3. Ein Release veröffentlichen, damit ein Update einmal durchläuft.
4. Ein physisches Gamepad an den Couch-Modus stecken.
