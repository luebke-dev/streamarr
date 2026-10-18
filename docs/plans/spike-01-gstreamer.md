# Spike 0.1 — WebRTC/GStreamer-Client gegen Lightrays

Status: Umgebung hergestellt, Spike läuft
Datum: 2026-09-27
Zielsystem: Fedora 44 (Bluefin), Wayland, AMD Strix Halo (Radeon 8060S, `radeonsi`)

## Ergebnis vorab: der Packaging-Befund

Die erste und wichtigste Erkenntnis des Spikes betrifft **nicht** den Code,
sondern die Abhängigkeiten. Ein GStreamer-Client, der H.264 über WebRTC
empfängt, scheitert auf Fedora an drei unabhängigen Stellen — jede davon
liefert einen irreführenden Fehler (`No such element or plugin`):

| Fehlt | Symptom | Lösung |
|---|---|---|
| `gstreamer1-plugins-bad-freeworld` | `vah264dec` nicht vorhanden | RPM Fusion free |
| `mesa-va-drivers-freeworld` | `vah264dec` vorhanden, aber **keine** H.264-Profile → Element wird nicht registriert | RPM Fusion free |
| `gstreamer1-libav` (RPM Fusion) | `avdec_h264` als Software-Fallback fehlt | RPM Fusion free |

**Warum das tückisch ist:** Fedora liefert VA-API nur für AV1, VP9 und JPEG.
`libgstva.so` ist vorhanden und lädt fehlerfrei — die H.264-Elemente werden
aber gar nicht erst registriert, weil der Treiber keine passenden Profile
meldet. `gst-inspect-1.0 vah264dec` sagt dann nur „No such element or plugin",
was nach einem fehlenden Plugin aussieht, in Wahrheit aber ein fehlender
VA-Treiber ist.

**Nachweis:**

```
# vorher (Fedora 42 oder ohne freeworld-Pakete)
$ vainfo | grep -c VAProfileH264
0
$ gst-inspect-1.0 vah264dec
No such element or plugin 'vah264dec'

# nachher (RPM Fusion free installiert)
$ vainfo | grep -c VAProfileH264
6
$ gst-inspect-1.0 vah264dec
OK
```

**Konsequenz für Phase 4 (Paketierung):** RPM Fusion free ist eine harte
Voraussetzung, nicht optional. Für die Distribution heißt das:

- **Fedora/RPM:** `rpmfusion-free-release` + `mesa-va-drivers-freeworld` +
  `gstreamer1-plugins-bad-freeworld` + `gstreamer1-libav` als Abhängigkeiten
  deklarieren. Ohne sie wäre die App auf Fedora **ohne Hardware-Decode** und
  ohne Software-Fallback — also de facto unbenutzbar.
- **AppImage/Flatpak:** die Codecs bündeln (Flatpak: `org.freedesktop.Platform.ffmpeg-full`).
- **Debian/Ubuntu:** `mesa-va-drivers` und `gstreamer1.0-libav` decken beides ab;
  dort existiert die Trennung nicht.
- **Windows:** entfällt, Decoder kommen über die mitgelieferten Plugins.

Das gehört in die Installationsdokumentation, sonst schlägt der erste Start auf
Fedora mit einem schwarzen Bild fehl.

## Verifizierte Elementkette

Auf Fedora 44 mit RPM Fusion free sind alle Elemente vorhanden, die der Client
braucht:

| Zweck | Element | Status |
|---|---|---|
| WebRTC | `webrtcbin` | OK |
| H.264 empfangen | `rtph264depay`, `h264parse` | OK |
| H.265 empfangen | `rtph265depay`, `h265parse` | OK |
| Jitter | `rtpjitterbuffer` | OK |
| Hardware-Decode | `vah264dec`, `vah265dec` | OK |
| Software-Fallback | `avdec_h264` | OK |
| Ausgabe | `glimagesink`, `autovideosink`, `appsink` | OK |
| Encoder (Server-Seite, zum Gegentesten) | `vah264enc`, `vah265enc` | OK |

## Entwicklungscontainer

Die ursprüngliche `tauri`-Distrobox lief auf Fedora 42; dort fehlen die
H.264-Pfade vollständig (VA-API nur AV1/VP9/JPEG). Ersetzt durch eine
Fedora-44-Box, passend zum Zielsystem:

```bash
distrobox create --name tauri44 --image quay.io/fedora/fedora:44 --yes
distrobox enter tauri44 -- bash -lc '
  sudo dnf install -y \
    "https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm"
  sudo dnf install -y --allowerasing \
    gstreamer1-devel gstreamer1-plugins-base-devel gstreamer1-plugins-bad-free-devel \
    gstreamer1-plugins-{base,good,bad-free,ugly-free} \
    gstreamer1-plugins-bad-freeworld gstreamer1-libav \
    mesa-va-drivers-freeworld ffmpeg libavcodec-freeworld libva-utils
'
```

!!! warning "Fedora 42 reicht nicht"
    Auf Fedora 42 fehlen die H.264-VA-Profile vollständig, unabhängig von den
    installierten Paketen. Die Box muss Fedora 44 (oder neuer) sein. Für CI
    heißt das: `ubuntu-latest` mit den apt-Paketen aus `.github/workflows/rust.yml`
    funktioniert für `lightrays`, aber ein **Client**-Build braucht zusätzlich
    einen Decoder (`libgstreamer-plugins-bad1.0-0` bringt `vah264dec` unter
    Ubuntu nicht mit — dort ist `gstreamer1.0-libav` der Weg).

## Offen

- Spike-Binary gegen den laufenden Lightrays-Server des Testservers.
- Latenzmessung (Glass-to-Glass) als Referenzwert für Phase 3.
- Verhalten bei H.265 (der Server sendet heute immer H.264, siehe
  `lightrays/src/encoder.rs::select_encoder`).

## Spike-Client: Ergebnis

Der Client liegt als `frontend/src-tauri/player/src/bin/spike-webrtc.rs` hinter dem
Feature `spike`. Er nutzt für jede Nachricht das echte
`streamarr_desktop_player::protocol`-Modul, prüft also den committeten
Wire-Vertrag gegen einen laufenden Server.

### Was nachweislich funktioniert

| Schritt | Status |
|---|---|
| WebSocket-Handshake mit Ticket | ✅ `HTTP 101 Switching Protocols` |
| Offer des Servers empfangen | ✅ 1798 Bytes |
| Answer erzeugt und gesendet | ✅ 1443 Bytes |
| ICE-Kandidaten getauscht | ✅ `ICE connection state: Checking` |
| Data Channel vom Server | ✅ `<- server opened data channel: input` |
| **Video dekodiert** | ✅ **420 Frames** — siehe „Decode-Beweis" unten |

Der Video-Decode war zunächst nicht nachweisbar, weil der Testserver zu 100 %
voll war und keine Session starten konnte. Er wurde deshalb **ohne Server**
nachgewiesen — siehe den nächsten Abschnitt.

## Decode-Beweis ohne Server

`frontend/src-tauri/player/src/bin/spike-local-webrtc.rs` (Feature `spike`) lässt zwei
`webrtcbin`-Elemente über **Loopback** miteinander verhandeln:

```
videotestsrc -> vah264enc -> rtph264pay -> webrtcbin (sendonly)
                                               |
                                    echtes ICE + DTLS + SRTP
                                               v
webrtcbin (recvonly) -> rtph264depay -> h264parse -> vah264dec -> fakesink
```

Ergebnis, reproduzierbar in drei Läufen:

```
sender   ICE: Checking -> Connected -> Completed
receiver ICE: Checking -> Connected -> Completed
sender peer connection:   Connected
receiver peer connection: Connected
decode branch using vah264dec (hardware)
ENCODED=421  DECODED=420
RESULT: 420 frames decoded from 421 encoded
```

**Warum das den Server nicht ersetzt, aber trägt:** Die Medienkette ist
identisch — `vah264enc` ist der Encoder, den der Server auf AMD wählt
(`lightrays/src/encoder.rs`), und Depayload/Parse/Decode sind dieselben Elemente
wie im echten Client. **Nur der Signalisierungstransport unterscheidet sich:**
hier werden die SDP direkt zwischen den Elementen übergeben statt über den
Lightrays-WebSocket. Damit ist die Kernannahme des Spielestreaming-Pfads
bewiesen, ohne auf einen funktionierenden Server zu warten.

### Vier Fehler, die dieser Aufbau gefunden hat

1. **`create-offer` vor PLAYING** scheitert mit „webrtcbin is closed". Der Fehler
   kommt **innerhalb des Promise** an, wo er als fehlendes `offer`-Feld erscheint
   — leicht als Parse-Problem fehlzudeuten.
2. **Ein nachträglich hinzugefügter Bin erbt den State nicht.** Der äußere
   Pipeline meldete PLAYING, während der Sender-Bin auf PAUSED blieb und nichts
   kodierte. `sync_state_with_parent()` behebt das. Die Bus-Ausgabe war der
   einzige Weg, das zu sehen.
3. **Zwei `webrtcbin` finden sich nicht von selbst.** Ohne manuelle
   `on-ice-candidate`-Weitergabe bleibt ICE auf „new", der Transport wird nie
   bereit und der Payloader blockiert nach **genau einem** Buffer
   (`ENCODED=1`). In Produktion übernimmt das der WebSocket.
4. **Der Decode-Zweig muss in dieselbe Pipeline.** Eine eigene Pipeline scheitert
   beim Verlinken mit „Pads have no common grandparent".

> Nebenbefund, der Zeit gekostet hat: `parse::launch` benennt Elemente als
> `rtph264pay0`, nicht `pay0`. Ein Buffer-Probe am falschen Element meldete
> `ENCODED=0` und sah nach einem Pipeline-Problem aus, war aber ein
> **Testfehler** — der Zähler hing an nichts. Elemente werden jetzt über den
> Factory-Namen gesucht.

### Fünf Fehler, die der Spike gefunden hat

Jeder davon wäre später im Produktivcode deutlich teurer geworden:

**1. Der Server ist immer der Offerer.** `lightrays/src/server.rs` verarbeitet
vom Client nur `answer`, `ice`, `keyframe`, `resize` — es gibt keinen Handler
für ein Client-Offer. Ein nativiver Client muss warten und antworten, genau wie
`useLightraysStreaming.js`.

**2. Der Server erstellt den Data Channel, nicht der Client.** Der Browser
registriert nur `pc.ondatachannel`. Ein eigener `create-data-channel`-Aufruf
führt zu zwei konkurrierenden Kanalbeschreibungen und die SDP-Verhandlung
schlägt fehl. Der Client muss `on-data-channel` abwarten.

> **Nachtrag (Präzisierung, nachdem die Serverlogs vorlagen).** Im Test wurden
> >100 Offer/Answer-Runden in 30 s beobachtet und zunächst dem Client
> zugeschrieben. Die Serverlogs zeigen bei demselben Lauf:
>
> ```
> 13:16:15  App 'Zelda…' launched → session 7b65ef0182904fdd
> 13:16:15  Compositor pipeline stopped      ← eine Sekunde später
> 13:16:16  Container stopped / Session stopped
> ```
>
> Die Session **starb sofort**. Der Server erzeugt bei *jedem*
> `on-negotiation-needed` ein neues Offer (`lightrays/src/webrtc.rs`); eine
> sterbende Session kann daher von sich aus neu verhandeln. Die Schleife ist
> damit **nicht eindeutig** als Client-Fehler belegt.
>
> Unabhängig davon bleibt die Korrektur richtig: Ein eigener Data Channel
> widerspricht dem Browserverhalten und dem Servercode, der den Kanal selbst
> anlegt (`lightrays/src/stream.rs::setup_data_channel`). Aber die Zahl
> „>100 Runden" ist **kein Beweis** für die Fehlerursache, und der
> Wiederholungstest gegen eine gesunde Session steht aus.

**3. `create-data-channel` liefert vor PLAYING `NULL`.** Die Bindings melden
das als Typfehler („Invalid return value"), nicht als `None`. Nachgewiesen mit
`examples/gtype-probe.rs`. (Für den Client irrelevant, seit Punkt 2 gilt, aber
dokumentiert für den Server-seitigen Vergleich.)

**4. ALPN muss auf `http/1.1` festgenagelt werden.** nginx bietet `h2` an und
bevorzugt es, wenn der Client beides anbietet — ein WebSocket-Upgrade über h2
ist nicht möglich, und der Handshake **hängt**, statt zu scheitern. Nachweis:

```
$ openssl s_client -connect 10.10.60.30:443 -servername streamarr.luebke.internal \
    -alpn "h2,http/1.1" | grep ALPN
ALPN protocol: h2            # Upgrade unmöglich
$ openssl s_client ... -alpn "http/1.1" | grep ALPN
ALPN protocol: http/1.1      # Upgrade funktioniert
```

**5. Split-DNS liefert eine tote Tailscale-Adresse.** `getent hosts` nennt
`10.10.60.30`, `getaddrinfo` (und damit jeder normale Client) liefert
`100.64.0.2`, was in einen Timeout läuft. Der Spike hat dafür ein
`SPIKE_RESOLVE=host:port:ip`-Flag, analog zu `curl --resolve`. **Das betrifft
die App selbst**: sie braucht entweder eine konfigurierbare Server-Adresse
(ohnehin geplant) oder einen dokumentierten Hinweis für Tailscale-Nutzer.

### Umgebungsabhängigkeiten (für CI und Paketierung)

Zusätzlich zu den RPM-Fusion-Paketen oben sind nötig:

- `libnice-gstreamer1` — ohne das startet `webrtcbin` **gar nicht**
  („libnice elements are not available", Pipeline geht nicht auf PAUSED)
- `openssl-devel` — für `native-tls`
- eine `tokio`-Runtime mit `sync`-Feature für die Signal-Kanäle

`native-tls` (nicht rustls) ist bewusst gewählt: es nutzt den System-Truststore,
in dem die interne CA liegt.

## Offen: Blocker durch den Testserver

Der Server ist **zu 100 % voll** (18 MB frei von 32 GB), daher schlägt Redis mit
`MISCONF ... unable to persist to disk` fehl und der Launch-Endpunkt antwortet
mit HTTP 500. Belegbarer Verursacher:

```
$ docker system df
Images        30   12   11.29GB   6.192GB (54%)
Build Cache   76    5    4.423GB   4.413GB
$ docker ps -aq --filter status=exited | wc -l
25          # verwaiste ffmpeg-Transcode-Container
$ docker images -f dangling=true -q | wc -l
4           # verwaiste Images, ~2 GB
```

Das ist **kein Code-Problem** und wird nicht ungefragt behoben: es ist der
Produktions-Testserver des Nutzers. Nötig wäre ein `docker container prune`
und/oder `docker image prune` (≈ 6 GB reclaimierbar), plus ein Blick auf die
Build-Cache-Nutzung (4,4 GB).

**Der Decode-Nachweis ist inzwischen auf anderem Weg erbracht** — über den
Loopback-Aufbau im Abschnitt „Decode-Beweis ohne Server". Offen bleibt nur der
Durchlauf gegen eine **echte** Lightrays-Session, also inklusive der
Signalisierung über den Server-WebSocket.

**Nachtrag 2026-10-18: der Engpass ist weg.** 99 verwaiste Transcode-Container
wurden entfernt (Folge des Restart-Loops, den `fix(playback): stop restarting a
transcode that already finished` beendet hat), der Build-Cache liegt bei 414 MB,
und das Dateisystem hat wieder Platz (107 GB frei von 128 GB, 17 % belegt). Die
verbleibende offene Frage ist unverändert der Durchlauf gegen eine echte
Lightrays-Session.
