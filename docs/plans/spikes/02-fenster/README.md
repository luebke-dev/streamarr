# Spike 0.2 — Messprogramme

Reproduktion der Messungen aus [spike-02-fenster.md](../../spike-02-fenster.md).
Diese Dateien sind **Messwerkzeuge, nicht Teil der App** — sie liegen hier, damit
die Gate-Entscheidung aus ADR 001 nachprüfbar bleibt und nicht auf einer
Behauptung steht.

Alle Programme laufen im Dev-Container, der die GTK-/WebKit-Entwicklungsheader
besitzt (siehe Doku „Umgebungsabhängigkeiten"):

```bash
distrobox enter tauri44
sudo dnf install -y webkit2gtk4.1-devel gtk3-devel chromium
```

## 1. Performance-Gate — WebKitGTK gegen Chromium

Zwei Läufe desselben Benchmarks. Der Vergleichswert ist nötig, weil eine
einzelne Zahl ohne Bezugspunkt keine Entscheidung trägt.

```bash
gcc gate-webkit.c -o gate-webkit $(pkg-config --cflags --libs webkit2gtk-4.1)

# WebKitGTK (die Engine, die Tauri benutzt)
./gate-webkit "$PWD/bench.html" 2560 1440

# Chromium, zum Vergleich
chromium-browser --enable-logging=stderr --v=0 \
  --user-data-dir=/tmp/cr --window-size=2560,1440 --start-fullscreen \
  file://$PWD/bench.html 2>&1 | grep -o 'BENCH_RESULT.*'
```

Ergebnisse: siehe Tabelle in der Spike-Doku (59,8 fps WebKitGTK gegenüber
59,4 fps Chromium bei 2560×1440).

> **Der Pfad muss absolut sein.** Ein relativer Pfad lässt WebKit `file:///`
> laden; die Seite führt dann kein JavaScript aus und der Lauf meldet
> stillschweigend `{}`. `gate-webkit.c` prüft das inzwischen selbst.

## 2. Fensterverhalten und Sink-Auswahl

```bash
gcc gate-overlay.c -o gate-overlay \
  $(pkg-config --cflags --libs gtk+-3.0 gstreamer-1.0 gstreamer-video-1.0 gstreamer-app-1.0)

SPIKE_SINK=waylandsink ./gate-overlay     # Linux: der funktionierende Weg
SPIKE_SINK=glimagesink ./gate-overlay     # bricht ab, siehe Doku
SPIKE_NO_HANDLE=1 ./gate-overlay          # Sink erzeugt eigenes Fenster
```

Erwartet für `waylandsink`: 480 dekodierte Frames, `fullscreen=yes` ohne
Aussetzer, UI versteck- und wiederherstellbar.

## 3. Positionierung — Wayland gegen X11

```bash
gcc zt.c -o zt $(pkg-config --cflags --libs gtk+-3.0)
./zt                              # MOVE_HONOURED=NO
GDK_BACKEND=x11 ./zt              # MOVE_HONOURED=yes
```

## 4. Stacking

```bash
gcc gate-zorder.c -o gate-zorder $(pkg-config --cflags --libs gtk+-3.0)
./gate-zorder
```
