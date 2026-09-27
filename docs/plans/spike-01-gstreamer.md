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
