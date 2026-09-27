# ADR 001: Shell-Technologie für die Streamarr Desktop App

Status: Angenommen
Datum: 2026-09-27
Kontext: Phase 0 des [Desktop-App-Plans](desktop-app.md)

## Fragestellung

Welche Technologie trägt die Desktop-App? Die Vorgabe „orientiere dich an
Jellyfin Desktop für Medien und moonlight-qt für Spiele" legt den *Player-Kern*
fest (libmpv bzw. GStreamer), aber nicht die *Shell* darum.

## Randbedingungen (gemessen, nicht angenommen)

| Randbedingung | Wert | Quelle |
|---|---|---|
| Bestehende UI | 41 511 Zeilen `.vue`, 15 570 Zeilen `.js`, 7 310 Zeilen i18n | `frontend/src` |
| Medien müssen nativ dekodiert werden | WebView-`<video>` kann kein HEVC (WebKitGTK), kein HDR, kein Audio-Passthrough | Tauri/WebKitGTK-Issues, `lightrays/src/encoder.rs`-Notiz |
| Spiele brauchen nativen WebRTC-Stack | WebKitGTK-WebRTC nur experimentell | webkit.org #274711, wry #85 |
| Spiele brauchen rohe Gamepads | WebKitGTK nutzt libmanette, unzuverlässig | tauri-plugin-gamepad README |
| Zielsystem des Entwicklers | **Wayland**, AMD Strix Halo | `XDG_SESSION_TYPE=wayland` |
| Streaming-Quelle | immer der Server (HLS/HTTP bzw. WebRTC) | Nutzervorgabe |

**Konsequenz:** Die UI bleibt die bestehende Web-Oberfläche. Ein Rewrite in
Slint/Qt/C++ (60k+ Zeilen) steht in keinem Verhältnis. Damit ist die Shell eine
*WebView-Shell*, und Video/Spiele laufen **immer** nativ daneben — die Shell
dekodiert nie selbst.

## Der entscheidende Befund

> `--wid` funktioniert unter Wayland nicht und wird es vermutlich nie:
> „It's not really possible. At least, the `--wid` option currently does not
> work on wayland and probably will never work (the wayland devs don't like
> embedding to arbitrary windows)."
> — mpv-player/mpv#9654; ebenso mpv#1242: „Just wayland is missing."

Das **widerlegt Weg B meines ursprünglichen Plans** für Linux. Unter Wayland
gibt es kein Reparenting in ein Fremdfenster; mpv/GStreamer bekommen ein eigenes
Toplevel. Jellyfin Desktop löst genau das mit einem `wl-proxy`, der mpv's
Wayland-Verbindung abfängt und die Surface als Subsurface dem eigenen Root
unterordnet (`jellyfin-desktop` Wiki, PR #563) — erheblicher Aufwand.

Damit ist die Einbettungsfrage **in jeder Shell dieselbe**: ein eigenes,
positioniertes Toplevel-Fenster über/neben der WebView. Die Shell-Wahl
entscheidet also *nicht* über die Videointegration.

## Optionen

| Option | UI | Video | Bewertung |
|---|---|---|---|
| **Tauri 2** | WebKitGTK / WKWebView / WebView2 | natives Overlay-Fenster | Rust durchgehend, klein, im Repo. WebKitGTK-Linux-Perf. ist dokumentiert problematisch |
| **Electron** | Chromium (gebündelt) | natives Overlay-Fenster | Rendering am konsistentesten, aber 150 MB+ und Node/N-API statt Rust für gst/mpv |
| **CEF eingebettet** | Chromium | natives Subsurface | Was Jellyfin in v3 macht; sehr hoher Integrationsaufwand, große Abhängigkeit |
| **Qt WebEngine** | Qt | libmpv via Render-API | Erzwingt C++/Qt *und* UI-Rewrite. Jellyfin hat es aufgegeben (→ CEF) |

## Entscheidung

**Tauri 2 bleibt, mit einer harten Architekturregel: die WebView ist reine
UI-Chrome, sämtliches Video und jede Spielausgabe laufen nativ.**

Begründung, gewichtet nach unseren Randbedingungen:

1. **Eine Sprache für den nativen Stack.** `lightrays` und die Downloader sind
   Rust, GStreamer und mpv haben erstklassige Rust-Bindings. Electron würde
   einen Node/N-API-Bruch mitten in den Player-Kern legen.
2. **Die WebKitGTK-Schwächen treffen uns nicht.** Sie liegen genau dort, wo wir
   die WebView bewusst *nicht* einsetzen: `<video>`-Codecs, WebRTC, Gamepad.
   Die verbleibende Schwäche — UI-Performance — ist real, aber unabhängig von
   Video und damit beherrschbar.
3. **Die Einbettung ist ein Toplevel-Problem** (siehe Befund oben), und das löst
   Tauri mit Multi-Window-Unterstützung plattformübergreifend gleich.
4. **Bundle-Größe.** Ein Desktop-Client, den Nutzer installieren, ist mit
   ~10 MB statt ~150 MB deutlich angenehmer.

## Konsequenzen

### Positiv
- Kein UI-Rewrite, kein Sprachwechsel, kleinste Pakete.
- Ein einziges Overlay-Konzept für Medien *und* Spiele.
- Der Player-Kern bleibt notfalls unabhängig testbar.

### Negativ / Risiko
- **WebKitGTK-UI-Performance auf Linux** ist das Hauptrisiko (dokumentierte
  Ruckel-/Blank-Window-Fälle, u. a. mit NVIDIA). Muss in Spike 0.2 gemessen
  werden. Betrifft die UI, nicht das Video.
- WebKitGTK ist im Umbruch (GTK4/WebKitGTK 6.0), Tauri zieht mit.

### Absicherung: Wechsel kostet wenig, wenn wir die Grenze jetzt ziehen
Alle nativen Fähigkeiten werden hinter **einer schmalen, shell-unabhängigen
IPC-Grenze** gekapselt (`player_*`-Commands + Event-Stream, siehe Plan §5).
Die UI ruft nie Tauri-APIs für den Player direkt auf, sondern geht durch
`src/services/nativePlayer.js`. Damit ist ein späterer Wechsel zu Electron eine
Neuimplementierung von ~10 Commands, nicht des Player-Kerns.

**Gate:** Wenn die UI-Performance in Spike 0.2 auf den Zielsystemen nicht
akzeptabel ist, wird diese ADR überarbeitet und auf Electron gewechselt. Das ist
der *einzige* Grund zu wechseln — nicht die Videointegration, die ist überall
gleich.

**Ergebnis (Spike 0.2, 2026-09-27): bestanden, Tauri bleibt.** WebKitGTK 2.54
erreicht 59,8 fps bei 2560×1440 und 58,4 fps bei 3840×2160, kein Frame über
50 ms. Chromium ist gleichmäßiger (p99 16,8 ms gegen 26 ms), was bei vsync ohne
sichtbare Folge bleibt.

Zu beachten: **das Gate ist nur auf Linux ein Gate.** Tauri nutzt auf Windows
WebView2 und damit Chromium, nicht WebKitGTK — die Engine-Schwäche, die diese ADR
als Risiko benennt, existiert dort nicht. Siehe
[spike-02-fenster.md](spike-02-fenster.md).

## Nicht gewählte Alternativen — Begründung

- **Electron jetzt:** löst kein Problem, das wir haben (wir dekodieren nicht in
  der Shell), kostet aber 15× Bundle und gibt die Rust-Durchgängigkeit auf.
- **CEF:** Jellyfins eigener Weg, aber der Aufwand (eigener CEF-Build, C++
  Brücke, Subsurface-Proxy) steht in keinem Verhältnis zu unserem Nutzen.
- **Qt:** erzwingt den UI-Rewrite, den wir explizit vermeiden.
- **Reines mpv/GStreamer ohne WebView (Slint):** schönste Videointegration, aber
  bedeutet, die gesamte Oberfläche neu zu bauen.

## Nachträglich zu korrigieren

- Plan §4.2: Weg B (`--wid`-Reparenting) ist für **Wayland nicht verfügbar**.
  Weg A (Overlay-Toplevel) ist nicht nur „Empfehlung für v1", sondern die
  einzige plattformübergreifend tragbare Variante.

## Update-Endpunkt: nicht an der Instanz

**Entscheidung:** Der Update-Feed ist ein statischer Wert im Bundle
(GitHub-Releases des Projekts), **nicht** eine Route des Streamarr-Servers,
gegen den die App gerade verbunden ist.

Die naheliegende Annahme ist die umgekehrte — „self-hosted, also liefert der
Server auch die App aus". Sie trägt nicht:

- **Die App ist ein Client, kein Bestandteil einer Instanz.** `ProfileStore`
  hält eine *Liste* von Servern (`desktop/player/src/profile.rs`); keiner davon
  ist der „Hauptserver". Welcher sollte den Update-Feed bestimmen?
- **Es wäre eine Codeverteilung durch Dritte.** Wer die Adresse eintippt, deren
  Feed die App folgt, könnte beliebigen Code auf das Gerät schieben. Das ist
  keine Funktion, die man baut.
- **Jede Instanz müsste Bundles mitpflegen.** Für ein selbstgehostetes Projekt
  wäre das eine dauerhafte Last ohne Gegenwert.
- **Es gibt nicht einmal eine Versionskopplung.** Gemessen: der Server prüft die
  Client-Version nicht (kein `X-Client-Version` in `backend/src/streamarr`).
  App- und Serverversion sind unabhängig; beide lesen heute zufällig
  `2026.2.1`, aber nichts verbindet sie. Ein instanzgebundener Feed würde eine
  Abhängigkeit erfinden, die es nicht gibt.

**Was die Instanz weiterhin bestimmt:** alles, wofür sie zuständig ist — Medien,
Spiele, Anmeldung, Profile. Nur eben nicht die Software, die auf dem Gerät läuft.

**Live geprüft:** Der Feed war von einem Rechner **ohne** Streamarr-Instanz,
ohne Profil und ohne Token abrufbar (`examples/update_probe.rs`). Er antwortet
heute `HTTP 404` (noch kein Release) — was die App als „noch keine Version"
liest, nicht als Fehler.

**Offen:** Der Signierschlüssel. Ohne ihn baut die App, aber sie aktualisiert
sich nicht; `createUpdaterArtifacts` wurde deshalb wieder aus
`tauri.conf.json` entfernt — mit gesetztem Schlüssel bricht `tauri build` sonst
mit „A public key has been found, but no private key" ab, und das hätte den
Bundle-Bau (Erfolgskriterium 8) zerlegt. Die Artefakte werden im Release-Lauf
über einen Config-Override eingeschaltet, wenn `TAURI_SIGNING_PRIVATE_KEY`
gesetzt ist.
