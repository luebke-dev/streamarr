# Spike 0.3: Medienwiedergabe über mpv

Datum: 2026-09-27
Status: abgeschlossen
Bezug: [Desktop-App-Plan](desktop-app.md) Aufgabe 0.3, offene Entscheidung §9.2

## Fragestellung

Aufgabe 0.3 verlangt: Datei abspielen, Play/Pause/Seek/Spurauswahl steuern,
Position zurückmelden. Zusätzlich beantwortet dieser Spike die **offene
Entscheidung Nr. 2 aus §9** des Plans: *libmpv in-process oder separater
mpv-Prozess?*

Die Aufgabe nennt außerdem `--wid` als Weg. Das ist nach
[Spike 0.2](spike-02-fenster.md) unter Wayland widerlegt (und generell nicht
verfügbar) und wird deshalb **nicht** verwendet.

## Entscheidung: separater Prozess mit JSON-IPC

**Der Prozess-Weg ist gewählt.** Gemessen mit `desktop/player/src/bin/spike-mpv.rs`
(Feature `mpv`), gegen einen echten Server-Stream und gegen lokale Testdateien.

| Kriterium | Ergebnis |
|---|---|
| mpv startet, IPC-Socket bereit | ✅ ~100 ms |
| Datei lädt und spielt | ✅ Positionsmeldung kommt an |
| **Direct Play (kein Transcode)** | ✅ Original-Matroska über `/api/stream/file` |
| Dauer bekannt (für Resume) | ✅ |
| Pause / Resume | ✅ |
| Seek | ✅ Zielframe exakt erreicht |
| Spurauswahl (Audio/Untertitel) | ✅ `sid` gesetzt und bestätigt |
| Geschwindigkeit | ✅ |
| GPU-Renderer aktiv (`vo-configured`) | ✅ |
| Beendet sauber, kein Zombie | ✅ |
| **Gesamt** | **12/12 Prüfungen** |

Beide Testdateien (mit und ohne Untertitelspur) laufen reproduzierbar 12/12.

### Warum der Prozess und nicht in-process

1. **Crash-Isolation.** Ein Absturz des Decoders darf die App nicht mitnehmen.
   libmpv in-process macht jeden Codec-Fehler zum App-Absturz.
2. **Keine native Link-Abhängigkeit.** Der Prozess-Weg braucht **keinen**
   C-Link gegen libmpv. Das Crate bleibt abhängigkeitsarm, und Paketierung wie
   CI werden deutlich einfacher (Phase 4).
3. **Der volle mpv-Pfad.** Der Plan (§4, „Warum nicht Browser-`<video>`") will
   `gpu-next` und HDR-Passthrough. Der Prozess bekommt alle Optionen; die
   Render-API ist eingeschränkter.
4. **Weniger Kopplung an mpv-Versionen.** Die IPC-Schnittstelle ist stabiler als
   die C-API.
5. **Wiederverwendung.** Nutzer können ihre `mpv.conf` mitbringen.

Preis: ein Prozessstart (~100 ms) und IPC-Marshalling. Bei Medienwiedergabe
spielt beides keine Rolle.

## Befund: Direct Play funktioniert über den Datei-Endpunkt, nicht über HLS

Der Plan spricht von „HLS-URL aus `/api/v1/stream`". Tatsächlich ist für einen
nativen Player der **direkte Datei-Endpunkt** der richtige Weg:

```
POST /api/play/{guid}?supported_video_codecs=...   → { token }
GET  /api/stream/file?token={token}                → Originaldatei, HTTP 206
```

Gemessen: `HTTP 206`, `Content-Type: video/x-matroska`, Range-Requests
funktionieren, **kein Transcode**. Der Play-Token allein genügt — mpv braucht
**keinen** `Authorization`-Header, was die Integration vereinfacht.
`playlist.m3u8` wäre der Transcode-Weg und damit genau das, was der Plan
vermeiden will.

### Der Server transkodiert derzeit trotzdem

Bei einem Test mit einem h264/AC3-Film meldete der Server
`playback_method: transcode` mit dem Grund `Audio: ac3 → aac`, obwohl Video
Direct Play hätte sein können. Ursache: Ohne mitgeschickte
`client_capabilities` nimmt der Server konservative Defaults an. Mit
`supported_video_codecs`/`supported_audio_codecs`/`client_max_resolution` als
**Query-Parameter** schrumpfte die Begründung auf die Audiospur.

**Für Phase 2 wichtig:** Der Client muss seine Fähigkeiten beim Play-Aufruf
mitgeben, sonst transkodiert der Server grundlos. Die Parameterübergabe ist
**Query**, nicht JSON-Body — der erste Versuch mit JSON-Body wurde stillschweigend
ignoriert.

## Sechs Fehler, die der Spike gefunden hat

Alle sechs waren echte Defekte im Client, nicht in mpv. Jeder hätte in Phase 2
Zeit gekostet:

**1. mpv's IPC ist streng typisiert.** `["observe_property", "1", "time-pos"]`
wird mit `{"error":"invalid parameter"}` abgelehnt und liefert **gar keine**
Events; `["observe_property", 1, "time-pos"]` funktioniert. Ein Helfer mit
`&[&str]` verdeckt diesen Fehler — er machte jede Zahl zu einem String, also
waren auch `seek 120`, `speed 1.5` und `sid 1` betroffen.
→ **Konsequenz für Phase 2: die Kommandoschicht wird typisiert, nicht als Strings.**

**2. `stderr` mit `Stdio::piped()` ohne Leser ist ein Deadlock.** mpv schreibt
genug Diagnose, um den 64-KiB-Puffer zu füllen, blockiert dann beim Schreiben und
sendet **keine IPC-Events mehr**. Der Client sieht das als „mpv antwortet nicht".

**3. Ein `BufReader` pro Aufruf verliert Daten.** `BufReader` liest voraus; was
gepuffert aber nicht konsumiert wurde, verschwindet beim Drop. Ein persistenter
Reader ist nötig.

**4. Große Antworten kommen fragmentiert.** `track-list` ist mehrere Kilobyte und
trifft in mehreren Stücken ein. Wer jedes Stück einzeln parst, hält eine korrekte
Antwort für eine leere Spurenliste. Es muss bis zum Zeilenumbruch akkumuliert
werden — und Bytes, die vor einem Timeout ankamen, dürfen nicht verworfen werden.

**5. Die Observer müssen nach `loadfile` registriert werden.** Vorher
registriert lieferten sie für die danach geladene Datei keine `time-pos`-Events.

**6. Ein blockierender Socket macht Timeouts wirkungslos.** Ohne
`set_read_timeout` kehrt `read_line` nie zurück und jede Deadline-Prüfung ist
tote Logik.

> Methodisch bemerkenswert: Aufgefallen sind diese Fehler erst, als eine
> **unabhängige Referenzimplementierung** (ein 30-zeiliger Python-IPC-Client)
> 496 Events empfing, wo der Rust-Client null empfing. Der Vergleich zweier
> Implementierungen desselben Protokolls war der schnellste Weg zur Ursache —
> nicht das Lesen des eigenen Codes.

## Umgebungsabhängigkeiten

- `mpv` 0.41.0 mit libplacebo 7.360.1 (Fedora 44, Dev-Container)
- `ffmpeg` — nur zum Erzeugen der Testdateien, **keine** Laufzeitabhängigkeit
- Kein `mpv-libs-devel` nötig: der Prozess-Weg linkt nichts

Die Testdateien werden im Spike-README beschrieben und sind nicht im Repo
(14 MB bzw. 4 MB; reproduzierbar per `ffmpeg`-Kommando).

## Grenzen

1. **`hwdec-current` war `"no"`** in dieser Messung — der Testinhalt (h264
   `testsrc`) wurde software-dekodiert. Dass die VA-API-Kette grundsätzlich
   vorhanden ist, zeigt Spike 0.1 (`vah264dec` vorhanden). Die Hardware-Decode-
   Rate eines echten 4K-Films ist noch **nicht** gemessen.
2. **HDR nicht geprüft.** Der Spike bestätigt nur, dass `--vo=gpu-next` aktiv ist
   (`vo-configured=true`). Echtes HDR-Passthrough braucht ein HDR-Display und
   HDR-Material; beides stand nicht zur Verfügung. Das gehört in Phase 2 (Aufgabe
   2.9).
3. **Kein echter Serverlauf für die Steuerungsprüfungen.** Der Testserver war
   während der Messung zu 100 % voll (0 Bytes frei), wodurch Redis mit
   `MISCONF` antwortete und `/api/stream/file` **HTTP 500** lieferte. Direct Play
   wurde deshalb über einen früheren, noch gültigen Token belegt (`HTTP 206`,
   Matroska), die Steuerungsprüfungen liefen gegen lokale Dateien.
   **Das ist keine Code-Ursache** — die Gegenprobe mit `curl` im Mount-Namespace
   ergab ebenfalls HTTP 500, bei gleichzeitig funktionierendem Zugriff auf
   `/api/auth/status`.
4. **Nur Linux.** Der Prozess-Weg ist plattformneutral, auf Windows aber nicht
   gemessen.
5. **Fenstereinbettung nicht Teil dieses Spikes** — sie ist in Spike 0.2
   geklärt.

## Ergebnis

| Frage aus 0.3 / §9.2 | Antwort |
|---|---|
| Steuerung aus der UI heraus | ✅ 12/12, inkl. Seek und Spurauswahl |
| Position wird zurückgemeldet | ✅ via `observe_property` |
| Direct Play ohne Transcode | ✅ `/api/stream/file`, HTTP 206, Matroska |
| **in-process oder Prozess?** | **Prozess** (JSON-IPC) — siehe Begründung |
| `--wid` verwenden? | **nein** — unter Wayland unmöglich (Spike 0.2) |
