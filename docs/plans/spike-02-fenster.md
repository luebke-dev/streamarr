# Spike 0.2: Fenster, Z-Order und das ADR-001-Performance-Gate

Datum: 2026-09-27
Status: abgeschlossen
Bezug: [Desktop-App-Plan](desktop-app.md) Aufgabe 0.2, [ADR 001](adr-001-desktop-shell.md)

## Fragestellung

ADR 001 hält an Tauri/WebKitGTK fest und benennt **WebKitGTK-UI-Performance**
als einziges echtes Risiko. Sie verpflichtet zu einer Nachprüfung, falls das
Gate auf den Zielsystemen reißt. Aufgabe 0.2 verlangt zusätzlich: *„Video
sichtbar, UI überlagerbar/ausblendbar, kein Flackern beim Fullscreen."*

Dieser Spike beantwortet beides mit Messwerten statt mit Annahmen.

## 1. Das Performance-Gate

### Verfahren

Gleicher Benchmark in beiden Engines, auf demselben Gerät, mit demselben
Fensterinhalt. Der Benchmark bildet bewusst die Form der echten Streamarr-UI ab:
eine lange Liste von Medienkarten, laufende CSS-Animation, skriptgesteuertes
Scrollen mit Layout-Zwang. Genau der Compositor-/Scroll-Pfad ist WebKitGTKs
dokumentierte Schwäche — Video ist es nicht, weil Video hier per Architektur
nativ läuft.

Gemessen wurden 12 Sekunden nach 5 Frames Einschwingzeit; `requestAnimationFrame`
liefert die Frame-Abstände.

| Auflösung | Engine | Ø ms | p50 | p95 | p99 | fps (Ø) | >20 ms | >50 ms |
|---|---|---|---|---|---|---|---|---|
| 2560×1440 | **WebKitGTK 2.54** | 16,71 | 17,0 | 20,0 | 22,0 | **59,8** | 31 / 707 | 0 |
| 2560×1440 | Chromium 154 | 16,82 | 16,7 | 16,8 | 16,8 | 59,4 | 5 / 707 | 0 |
| 3840×2160 | **WebKitGTK 2.54** | 17,12 | 17,0 | 21,0 | 26,0 | **58,4** | 70 / 689 | 0 |
| 3840×2160 | Chromium 154 | 16,82 | 16,7 | 16,7 | 16,8 | 59,4 | 4 / 708 | 0 |

### Bewertung

**Das Gate ist bestanden.** WebKitGTK erreicht 58–60 fps bei 4K und bleibt damit
im vsync-Limit; kein Frame überschreitet 50 ms, die p99 liegt bei 26 ms. Die
Ruckel-Berichte, die ADR 001 als Risiko nennt, treten hier **nicht** auf — mit
AMD Strix Halo (Radeon 8060S) und WebKitGTK 2.54 auf Wayland.

Ehrlicher Unterschied: Chromium ist *gleichmäßiger*. WebKitGTK hat einen
schwereren Tail (70 Frames über 20 ms bei 4K gegenüber 4 in Chromium). Bei 60 fps
ist das ohne sichtbare Folge, aber es ist der Grund, warum eine schwere UI auf
WebKitGTK früher an Grenzen stößt als auf Chromium.

**Kein Wechsel zu Electron.** Die Messung gibt dafür keine Grundlage her. Die
ADR-001-Begründung (eine Sprache, ~10 MB statt ~150 MB, WebKit-Schwächen liegen
dort, wo wir die WebView nicht nutzen) trägt weiter. Der dokumentierte
Rückfallweg bleibt: die IPC-Grenze ist schmal genug, dass ein Wechsel nur die
Shell betrifft.

## 2. Fensterintegration (Weg A)

### Befund: Positionierung ist unter Wayland nicht möglich

Messung mit zwei GTK-Topleveln (`zt.c`): `gtk_window_move(120, 90)` ergab

```
GDK_BACKEND=wayland-0
REQUESTED (120,90) -> BEFORE (26,23) AFTER (26,23)
MOVE_HONOURED=NO

GDK_BACKEND=:0        # XWayland
REQUESTED (120,90) -> BEFORE (120,90) AFTER (120,90)
MOVE_HONOURED=yes
```

Das bestätigt und **verschärft** den ADR-Befund zu `--wid`: es ist nicht nur das
Reparenting, das unter Wayland fehlt — ein Client darf seinen Toplevel **gar
nicht positionieren**. Damit ist die im Plan §4.2 formulierte Idee „an die
WebView-Position gepinnt" unter Wayland **nicht umsetzbar**.

Zusätzlich: GNOME/Mutter liefert **kein `layer-shell`** (im System sind keine
entsprechenden Protokolle vorhanden). Ein echtes Overlay mit Pixelkontrolle ist
auf GNOME also nicht erreichbar.

### Konsequenz für die Architektur

Weg A wird präzisiert — die Umsetzung hängt nicht mehr an Koordinaten:

| Modus | Vorgehen | Trägt auf |
|---|---|---|
| **Wiedergabe** | Video-Toplevel im **Fullscreen**, UI-Fenster wird versteckt | Wayland, X11, Windows |
| **HUD/Menü über Video** | HUD wird **in das Video-Toplevel** gezeichnet (GTK-Overlay bzw. GStreamer-`overlay`-Element), nicht als zweites Fenster | alle |
| **Positioniertes Fenster** | nur X11 und Windows; unter Wayland nicht verfügbar | X11, Windows |

Das ist eine echte Planänderung und wird in §4.2 nachgezogen. Sie kostet wenig:
der Fullscreen-Fall ist der, den Couch-Modus und Spielestreaming ohnehin
brauchen.

### Befund: Video rendert zuverlässig, Fullscreen flackert nicht

Messung mit `waylandsink` in einem eigenen GTK-Fenster, GDK-`wl_surface` per
`gst_video_overlay_set_window_handle` übergeben (`gate-overlay.c`):

```
sink=waylandsink
backend=wayland sink_has_video_overlay=yes
frames_decoded=60 → 120 → 180 → 240
fullscreen=yes frames_after_switch=300     # Fullscreen ohne Aussetzer
step: hiding UI window
frames_decoded=300 → 360
step: UI restored, frames=390
frames_decoded=420
FINAL frames_decoded=480                   # durchgehend, kein Neustart nötig
```

480 dekodierte Frames, **kein Abbruch beim Fullscreen-Umschlag**, kein
Neu-Setzen des Window-Handles nötig, UI während laufender Wiedergabe versteck-
und wiederherstellbar. Das Abnahmekriterium aus Aufgabe 0.2 ist damit erfüllt.

### Befund: `glimagesink` und `waylandsink` sind nicht austauschbar

| Sink | `GstVideoOverlay` | GDK-`wl_surface` übernehmbar |
|---|---|---|
| `waylandsink` | ja | **ja** |
| `glimagesink` | ja | **nein** — bricht ab mit `GstGLBaseMemory ... assertion failed` bzw. `Failed to flush Wayland connection` |
| `gtksink` | nein | — (bringt eigenes Widget mit) |

`glimagesink` verlangt eine eigene GL-Surface; GDKs Surface führt zum Absturz.
Für den Linux-Weg ist damit **`waylandsink` der Sink der Wahl**, nicht
`glimagesink`. Auf Windows bleibt `d3d11videosink`.

### Befund: Stacking-Anfragen werden akzeptiert

`gtk_window_present()` auf dem Overlay lässt beide Fenster sichtbar und liefert
keinen Fehler — unter Wayland wie unter X11. Da GDK keine Z-Order-Abfrage
anbietet, ist das ein Verhaltens-, kein Beweistest. Deshalb bleibt **Verstecken
die primäre Strategie** und „Raise" nur eine Zugabe; das HUD gehört ohnehin in
das Video-Toplevel.

## 3. Umgebungsabhängigkeiten (für Phase 4)

Im Dev-Container `tauri44` (Fedora 44) zusätzlich installiert:

- `webkit2gtk4.1-devel` 2.54.0, `gtk3-devel` 3.24.52 — Tauri-Grundlage
- `librsvg2-devel`, `libappindicator-gtk3-devel`
- `chromium` — nur für den A/B-Vergleich, **nicht** Laufzeitabhängigkeit
- Für den Overlay-Weg: GTK3 + GStreamer, **kein** `gtksink` nötig

## 4. Grenzen dieser Messung

1. **Nur Linux.** Aufgabe 0.2 verlangt auch Windows. Die Windows-Messung steht
   aus (kein Testsystem in dieser Umgebung) und ist offen — sie ist der einzige
   noch fehlende Teil des Gates.
2. **Ein Gerät.** AMD Strix Halo mit funktionierender Hardwarebeschleunigung. Die
   in ADR 001 genannten Ruckel-Fälle betreffen überwiegend NVIDIA; die sind hier
   nicht reproduzierbar.
3. **Synthetische UI.** Der Benchmark bildet Form und Last der echten UI nach,
   ersetzt aber keine Messung an der echten `frontend/`-Oberfläche. Die gehört in
   Phase 1 nach dem ersten lauffähigen Tauri-Fenster nachgeholt.
4. **X11 nur über XWayland** geprüft, nicht auf einem echten X11-Server.

## Ergebnis

| Kriterium aus 0.2 | Ergebnis |
|---|---|
| Video in eigenem Overlay-Fenster sichtbar | ✅ 480 Frames |
| UI ausblendbar und wiederherstellbar | ✅ ohne Video-Unterbrechung |
| Kein Flackern beim Fullscreen | ✅ kein Aussetzer, kein Re-Handle |
| Z-Order/Raise | ✅ akzeptiert (verhaltensgeprüft) |
| Positionierung | ❌ unter Wayland unmöglich → Architektur angepasst |
| Performance-Gate (Linux) | ✅ 58–60 fps bei 4K |
| Performance-Gate (Windows) | ⏳ offen |

**Gate-Entscheidung: Tauri 2 bleibt.** Kein Wechsel zu Electron.
