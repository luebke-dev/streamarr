# Abschluss der Desktop-App (Phasen 2–5)

**Stand:** alle sieben Arbeitspakete abgeschlossen · 63 Commits auf `feat/desktop-app`
**Nicht gepusht, nicht ausgeliefert, kein Servereingriff.**

Diese Seite liest die zehn Erfolgskriterien Punkt für Punkt gegen und trennt
scharf zwischen *gemessen* und *offen*.

## Der Grund, der keiner mehr ist

Diese Seite hat alle offenen Punkte mit **einer** Ursache erklärt: der Testserver
habe keine Datenbank mehr. `app-db-1` sei zerstört, ein verwaister
Docker-Netzwerk-Endpunkt halte die Adresse, und die Reparatur brauche einen
Docker-Daemon-Neustart, den der Auftraggeber abgelehnt habe.

**Das ist überholt, und zwar messbar überholt.** Am 11.10. gemessen:

* `app-db-1` läuft seit **13 Tagen** und meldet `healthy`;
* `/api/auth/status` → 200 mit `local_auth_enabled: true`;
* `/api/auth/me` → 200 mit einem echten Benutzer, und dieser Aufruf **braucht die
  Datenbank** — er sucht den API-Schlüssel nach.

Es gab also keinen Grund, die Live-Nachweise zu unterlassen, und sie sind jetzt
gemacht worden (siehe unten). `desktop-testserver-stand.md` bleibt als Protokoll
stehen; die Reparaturanleitung darin ist gegenstandslos geworden.

Was von den damaligen Befunden bleibt: der verwaiste Endpunkt und der volle
Host-Datenträger waren echte Beobachtungen — nur war die Schlussfolgerung daraus
zu weitgehend.
begründet, ist damit **jedenfalls teilweise vorbei**. Ob die Datenbank zurück ist,
ist damit nicht belegt (beide Endpunkte können ohne sie antworten), und die drei
Live-Nachweise sind weiterhin **nicht versucht** — es bleibt bei offen.

Deshalb sind genau drei Dinge offen, die eine Live-Verbindung brauchen: **Login,
Medienwiedergabe und Spiel-Streaming gegen den echten Server.**

## Die zehn Kriterien

| # | Kriterium | Stand |
|---|---|---|
| 1 | Medien über den nativen mpv-Kern | **live nachgewiesen**, samt Login und Sitzung über einen Neustart |
| 2 | HDR10 durchgereicht oder nachweisbar gemappt | **gemessen** |
| 3 | Spiele über GStreamer/WebRTC nativ | **live nachgewiesen bis zur Aushandlung**; Medienpfad serverseitig blockiert |
| 4 | Couch-/Big-Picture-Modus in der UI | **gebaut**, ohne Controller |
| 5 | Alle Rust-Crates grün | **gemessen** |
| 6 | Frontend ohne neue Fehler | **gemessen** |
| 7 | Golden-Tests des Wire-Vertrags | **gemessen** |
| 8 | Installierbare Pakete, Linux und Windows | **Linux gemessen**, Windows in CI |
| 9 | Doku und CI | Doku **gemessen**; CI **nie gelaufen** |
| 10 | Server-Zwischenstand festgehalten | **gemessen** |

## Die drei Live-Nachweise, am 11.10. gemacht

### Medien: läuft — und lief vorher überhaupt nicht

Ein echtes Medium über den echten Server: Position 0,00 s → 2,00 s,
`ERGEBNIS: Wiedergabe über den nativen mpv-Kern, Position läuft`. Dabei wurden
mpvs **eigene** Spuren live gelesen (`#1 Video h264`, `#1 Audio ger aac`) — das ist
die Liste, die die Oberfläche jetzt als Auswahl anbietet.

Es war kein Nachweis, der nur gefehlt hätte: **vorher spielte kein einziger Frame.**
Die Ursache stand im mpv-Protokoll nach **124 abgewiesenen Segmentversuchen** — die
HLS-Playlist trägt das Token für sich selbst, die Segment-URLs darin nicht, und ein
relativer Verweis gegen eine Basis mit Query verliert die Query. Behoben, indem das
Play-Token als `Authorization`-Header mitgeht. Details im Commit `f45a584`.

**Direct Play bleibt auf dieser Instanz unerreichbar**, und zwar nicht wegen des
Clients: alle vorhandenen Filme haben ac3- oder dts-Ton, und der Server bildet beide
**unbedingt** auf aac ab — auch wenn der Client ac3 als unterstützt meldet und der
Server diese Meldung zurückspiegelt. Der Nachweis ist also der **Transcode-Pfad**.
Nebenbei gemessen: die Bibliothek hat genau **einen** abspielbaren Film, die anderen
19 antworten `status: searching`.

### Spiele: der Client war nie ein WebRTC-Peer

Der Live-Lauf gegen echten Lightrays: `HTTP 101 Switching Protocols`, dann für immer
`Negotiating`. `create-answer`, `set-remote-description` und `set-local-description`
kamen in Shell und Kern **null** mal vor. `ClientMessage::Answer` existierte die ganze
Zeit und war als „SDP answer to the server's offer" dokumentiert — nur gebaut und
gesendet hat es nie jemand. Keine Remote-Description, also kein ICE, kein Kandidat,
kein DTLS, kein Bild.

Warum keine Prüfung das sehen konnte: in `game-pipeline-check` verhandeln zwei
`webrtcbin`-Elemente im **selben Prozess**, und das **Testbinary** erledigt
`create-offer`/`create-answer` selbst. Beide Peers sind dort echt — die Shell war
nie einer von ihnen. Genau die Grenze, die diese Seite benannt hatte.

Nach dem Fix (`a601b47`): `Angebot gesetzt`, `Antwort gesendet (true)`, ICE startet.

**Was bleibt, ist serverseitig.** Die Diagnose ist eindeutig:

* das Angebot des Servers kommt mit **0 Kandidaten im SDP** und tröpfelt sie danach —
alle auf `172.21.0.3`, der **Docker-internen Adresse des Spielcontainers**;
* die Kandidaten des Clients sind korrekt, inklusive `10.10.20.161`, seiner echten
VLAN-20-Adresse;
* als ICE-Server wird nur ein öffentliches STUN angeboten, das einem Peer ohne
routbare Adresse nicht helfen kann.

Der Client verhandelt also richtig, und der Medienpfad scheitert daran, dass der
Server eine Adresse anbietet, die außerhalb seines Docker-Netzes niemand erreicht.
Das ist eine Ausrollfrage (externe Adresse, Portweiterleitung oder TURN), kein
Client-Fehler — und es steht zum ersten Mal als **gemessene** Tatsache da statt als
Vermutung. Behoben wurde es nicht; dafür braucht es eine Serveränderung.

### Login: läuft, samt Sitzung über einen Neustart

Der Anmeldeweg ist nachgewiesen: echte Anmeldung in der App → Token im
Schlüsselbund (`media.streamarr.desktop` / `session`, 694 Zeichen mit
`access_token`, `refresh_token`, `token_type`, `expires_in`) → **Neustart der App →
kein neuer Login** und die vollständige authentifizierte Startseite
(`/api/libraries`, `/api/viewing-history/continue-watching`,
`/api/media/shows/*/resume`, `favorites`, `lists`, `settings/*`).

Auch hier war es kein fehlender Nachweis, sondern **die App war unbenutzbar**, und
zwar aus drei unabhängigen Gründen (Commit `30fe3a0`):

* **Der Transport-Adaper schluckte Tauris eigenen Befehlskanal.** Tauri schickt
  jeden Befehl als `fetch('http://ipc.localhost/<befehl>')`, und der Adapter
  ersetzte `globalThis.fetch`: `invoke` rief den Adapter, der Adapter rief
  `invoke`, und die Fehlermeldung **verdoppelte** sich pro Runde bis
  `RangeError: Out of memory`. Am Shell-Log gemessen: **kein einziger**
  Tauri-Befehl erreichte Rust, obwohl die Seite einwandfrei aussah.
* **Kein POST trug einen Body.** `body=0` beim Login, Antwort des Servers
  `422 {"loc":["body"],"msg":"Field required"}` — liest sich wie ein
  Berechtigungsproblem und ist ein fehlender Body, weil axios dem Adapter ein
  fertiges `Request` übergibt und nur `init.body` gelesen wurde.
* **Der Refresh-Token wurde nie geschickt.** `stores/auth.js` setzt den
  Authorization-Header nur bei `isNativePlatform()` — Capacitor, in Tauri `false`,
  dieselbe Verwechslung wie in Aufgabe 0.5. Also `400` beim Refresh und ein
  Login-Formular, während ein gültiger Refresh-Token im Schlüsselbund lag. Der
  Token selbst funktionierte nachweislich: als er mitgeschickt wurde, antwortete
  `/api/auth/refresh` mit **200**.

Zur Korrektur der früheren Fassung: dort stand, der Testbenutzer habe kein
Passwort und es habe „noch nie ein Login abgeschlossen". Beides war eine
Fehlinterpretation der Messung — der fehlende Schlüsselbund-Eintrag war das
Ergebnis der drei Fehler oben, nicht der Grund.

## Was gemessen ist

**Rust.** `desktop/player` 514 Tests feature-frei und mit `mpv`/`spike`, 537 mit
`gamepad`. `frontend/src-tauri` 144 Tests ohne Zutaten und mit `custom-protocol`,
152 mit `gamestream` — in beiden Kombinationen mit `custom-protocol`. `cargo fmt
--all --check` und `clippy --all-targets -- -D warnings` sauber in **allen acht**
Konfigurationen (vier je Crate).

**Frontend.** 430 Tests grün, 24 Fehler in 9 Dateien — genau die dokumentierte
Baseline, unverändert über die gesamte Arbeit. ESLint sauber, `npx quasar build`
erfolgreich. `mkdocs build --strict` exit 0, 0 Warnungen; zusätzlich sind alle
internen Anker aufgelöst worden, weil `--strict` sie **nicht** prüft.

**Pakete.** `.deb` (10,8 MB), `.rpm` (10,8 MB) und AppImage (120 MB) gebaut und
geöffnet. Jede direkt gelinkte Bibliothek ist deklariert, geprüft von
`desktop/scripts/check_bundle_deps.sh` — das Skript hat dabei **acht** fehlende
Abhängigkeiten gefunden, darunter `libudev1` (durch die eigene
Controller-Unterstützung) und drei GStreamer-Pakete (durch die Spiel-Verdrahtung).

Die Artefakte liegen **nicht mehr auf der Platte**: sie fielen dem Aufräumen nach
dem vollen Host-Datenträger zum Opfer. Die Zahlen oben stammen aus dem damaligen
Lauf und sind heute nicht mehr nachprüfbar — ein Paket neu zu bauen ist der
Durchstich dafür.

**Die App läuft.** Live gestartet und am Prozess belegt: ein Wayland-Fenster
(`wayland-cursor`-Deskriptor), GPU-Zugriff (`/dev/dri/renderD128`, dreifach
geöffnet), 60 Threads, darunter `gilrs` (der Controller-Leser) und `VBlankMonitor`
(echtes Rendering, kein Null-Backend).

**Sie läuft als eigenständiges Programm.** Acht Stunden am Stück, dann über das
Hauptfenster geschlossen, Exit 0 — kein Absturz. Und sie lädt **ihr eigenes UI**:
0 Verbindungen auf Port 9000 statt eines Dev-Servers.

**Korrektur zu einer früheren Fassung dieser Seite.** Hier stand, die App habe
„2 Verbindungen zum Server auf 443" gehabt, und das sei der Beleg, dass die
Oberfläche lädt und mit der API spricht. Der zweite Teil ist **falsch**, und der
Fehler ist lehrreich: dieselbe Messung zeigte später, dass **kein einziger**
Tauri-Befehl die Shell erreichte — der IPC-Kanal war tot (siehe „Der Client war
kein WebRTC-Peer", Abschnitt zur Aushandlung). Die zwei Verbindungen waren
vermutlich Reste im `TIME_WAIT` und sind **kein** Beleg für irgendetwas. Wer eine
Prozessliste liest, muss den Zustand der Sockets prüfen und nicht ihre Zahl.

**Ein echter Fehler, gefunden durchs Starten.** Ein direkt gebautes Binary zeigte
statt der Oberfläche eine Browser-Fehlerseite. Ursache: `frontend/src-tauri`
deklarierte das Feature `custom-protocol` **nie**, und Tauri wählt zwischen
Dev-Server und eingebetteten Dateien nach diesem Feature, **nicht** nach dem
Build-Profil (`is_dev()` ist `!cfg!(feature = "custom-protocol")`). Jedes direkte
`cargo build`, auch `--release`, lud damit `http://localhost:9000`. Gemessen: das
Debug-Binary enthielt die Zeichenkette `localhost:9000`, obwohl `dist/spa` fertig
gebaut war. `tauri build` setzt das Feature selbst — deshalb waren die Pakete
immer in Ordnung und der Fehler blieb unsichtbar, bis jemand ein Binary allein
startete. Erschwerend: auf 9000 lauschte der Dev-Server eines **fremden Projekts**,
der die Verbindung annahm und sofort abbrach — das sah nach Netzproblem aus,
während der Server `/api/auth/status` mit 200 beantwortete.

**HDR.** Der EDID/CTA-861-Parser liest den echten Monitor und erkennt ihn als
HDR10-fähig, deckungsgleich mit `edid-decode`. Der Live-Test fand dabei einen
Fehler in meinen eigenen Unit-Tests: PQ ist **Bit 2**, nicht Bit 1.

**Die Spiel-Pipeline.** `DECODED=10`, `INPUT_SENT=6 INPUT_RECEIVED=6` über einen
echten WebRTC-Datenkanal, reproduzierbar. Die `mouseabs`-Zeile zeigt die
Letterbox-Korrektur in Aktion: aus einem Punkt in der Flächenmitte wird
`x=640, y=360` — die Mitte des *Bildes*.

## Kriterium 9: der CI-Workflow ist geschrieben, aber nie gelaufen

Ehrlich benannt, weil es ein Erfolgskriterium ist und in der ersten Fassung
dieser Seite fehlte: **`.github/workflows/desktop.yml` hat nie ausgeführt.**

Der Branch wurde nie gepusht — das war ausdrücklich so vereinbart — und ohne Push
läuft kein GitHub-Actions-Job. Was geprüft ist, ist die *Substanz* des Workflows:

* alle 30 `run:`-Skripte bestehen `bash -n`,
* die Schritte decken ab, was sie sollen (Baseline-Gate `>24`, Bundle-Job,
  `recvonly`-Prüfung im Paket, Windows-Job mit Artefakt-Zählung,
  GStreamer-Versionsschranke, `gamestream`-Variante),
* und jeder Schritt wurde inhaltlich lokal nachgestellt.

Das ist **nicht** dasselbe wie ein grüner Lauf. Ein grüner Lauf braucht einen
Push, und der ist nicht freigegeben.

## Was offen ist, und warum

**Login.** Siehe oben: der Anmeldeweg der App ist nicht nachgewiesen, weil kein
Passwort hinterlegt ist und der Auftraggeber sich selbst anmelden wollte. Das ist
der einzige der drei Live-Nachweise, der noch aussteht — und er hängt an einer
Anmeldung, nicht an einem Serverproblem.

**Ein Spiel auf dem Bildschirm.** Der Pipeline-Beweis ist Schleife-zu-Schleife und
sagt nichts über die Interoperabilität mit Lightrays — das ist jetzt geschlossen:
der Client verbindet sich (`HTTP 101`), setzt die Remote-Description, erzeugt die
Antwort, **sendet sie** und startet ICE. Was fehlt, ist das Bild, und der Grund ist
gemessen und serverseitig: das Angebot nennt nur `172.21.0.3`, die Docker-interne
Adresse des Spielcontainers. Kein Kandidat außerhalb dieses Netzes, kein TURN — also
kein Medienpfad. Der Client ist damit nachweislich richtig und das Ausrollen nicht.

**Ein Support-Bericht, der ankommt.** Die Logik und der Dialog sind getestet, der
Rundlauf ist es nicht. Am 11.10. war `POST /api/client-logs` erreichbar — der
Rundlauf ist trotzdem nicht ausgeführt worden, und ein Bericht lädt Log-Auszüge
hoch, was vorher ein Leck war (siehe `752cb43`).

**Tastatur und Maus im Spiel.** Gamepads gehen direkt (die Shell liest sie über
`gilrs`, deshalb teilen sich Couch- und Spielweg einen Leser). Für Tastatur und
Maus müsste das **Spiel-Fenster** der Shell seine eigenen Tastenereignisse
weiterleiten — die Seite hat den Fokus nicht, und Ereignisse, die sie nie
empfängt, kann sie nicht senden. Das ist offen und im Code als solches benannt,
statt Listener zu installieren, die nichts tun könnten.

**Couch-Modus mit einem echten Controller.** Auf dieser Maschine gibt es kein
Gamepad. Die Geometrie, die Wiederholregel und die Shell-Befehle sind getestet,
der Tastaturweg durchgängig — der Controller-Weg ist nie von einem Menschen
gedrückt worden.

**Windows.** NSIS und MSI werden in der CI auf `windows-latest` gebaut, und der
Job prüft, dass beide Artefakte existieren. Aber **kein Mensch** hat einen dieser
Installer ausgeführt. Es gibt in diesem Projekt keinen Windows-Host.

Das Windows-Paket **zeigt die Bibliothek, spielt aber nichts ab**: Spiele brauchen
GStreamers MSVC-Entwicklungspaket (auf dem Runner nicht vorhanden), und die
Medienwiedergabe wird über einen **Unix-Socket** gesteuert — unter Windows wäre es
eine Named Pipe, und dieser Client ist nicht geschrieben. `Mpv::start` liefert dort
eine Erklärung, statt einen Prozess zu starten, mit dem es nicht reden kann. Das
Paket entsteht ohne `gamestream`, damit aus „nicht gebaut“ wenigstens „gebaut, mit
benannter Lücke“ wird.

**OIDC-Login.** Der Testserver hat `oidc_enabled: false`.

**AppImage-*Einhängen*.** FUSE funktioniert im Baucontainer nicht. Der
*entpackte* AppImage läuft nachweislich (über `AppRun`); das direkte Starten von
`usr/bin/Streamarr` scheitert erwartungsgemäß, weil `AppRun` die WebKit-Pfade
setzt.

**Ein Update, das installiert wurde.** Es gibt kein Release.

**Der Rechner dieser Tests ist am Speicherlimit.** WebKit meldet beim Start
zweimal `Unable to shrink memory footprint of process (16654 MB) below the kill
threshold (16384 MB). Killed`. Gemessen ist das **nicht** der Speicher der App:
die lag bei 59–145 MB. Die Cgroup der Sitzung steht bei 35 GB und der Swap ist
vollständig belegt (8 von 8 GiB), und WebKit liest unter Distrobox einen größeren
Bereich als den eigenen Prozess. Die App hat es beide Male überlebt und sauber
beendet. Es bleibt ein Umgebungsvorbehalt: wer auf einer Maschine mit freiem
Speicher testet, sieht die Meldung vermutlich nicht — und ob ein gekillter
WebKit-Teilprozess einmal die Oberfläche leert, ist damit **nicht** ausgeschlossen,
sondern nur nicht aufgetreten.

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
