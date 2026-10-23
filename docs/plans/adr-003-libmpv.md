# ADR 003 — Medienwiedergabe über libmpv im App-Prozess

**Status:** umgesetzt (2026-10-23) — Spike belegt, Render-Schicht und Wiedergabeweg stehen
**Entschieden:** 2026-10-22
**Ersetzt teilweise:** ADR 001, soweit es den getrennten mpv-Prozess betrifft

## Kontext

Die App startet mpv heute als **eigenen Prozess** und steuert ihn über JSON-IPC
(`frontend/src-tauri/player/src/mpv.rs`). Das Video erscheint in einem **eigenen Vollbild-Fenster**,
die Oberfläche verschwindet dahinter. Gemessen und belegt: Direct Play über
`GET /api/stream/file?token=…`, `VO: [gpu-next]`, Positions- und Spurmeldungen kommen
zurück.

Der Vergleich mit Jellyfin Desktop fällt trotzdem schlecht aus: dort liegt das Bild **im
Fenster der App**, mit deren eigener Bedienung darüber. Der Nutzer hat entschieden, diesen
Weg zu gehen.

## Was geprüft wurde, bevor entschieden wurde

* **`--wid` ist unter Wayland keine Option.** mpv bettet nur in X11-, Win32- und
  Cocoa-Fenster ein; die Wayland-Unterstützung ist in den Upstream-Issues (#1242, #9654)
  ausdrücklich als „nicht möglich und wahrscheinlich nie" beschrieben — Wayland erlaubt
  kein Einbetten fremder Oberflächen.
* **libmpv mit Header, EGL 1.5 und `wayland-egl` sind auf der Zielmaschine vorhanden**
  (libmpv 2.5.0, 66 DRI-Treiber, AMD).
* Die Render-API (`mpv_render_context`) ist der von mpv vorgesehene Weg für eigene GUIs.

## Entscheidung

Die Medienwiedergabe läuft künftig über **libmpv im App-Prozess**, gerendert mit der
**Render-API** in eine **Wayland-Subsurface unter der WebView**. Damit gilt:

* ein Fenster; die Oberfläche bleibt sichtbar und liegt über dem Bild;
* die Bedienelemente sind unsere, nicht mpvs OSD;
* kein Prozessstart, keine IPC-Verzögerung, ein Zustand statt zwei.

Die Spielwiedergabe bleibt unberührt (GStreamer, eigenes Overlay).

## Konsequenzen

**Gewonnen:** Integration, wie sie der Nutzer erwartet; ein Zustandsmodell; die
vorhandene Wiedergabe-Oberfläche (`NativePlaybackView.vue`) wird zur echten Steuerung.

**Bezahlt:**

* **Prozessisolation entfällt.** Ein Absturz in libmpv beendet die App. Beim bisherigen
  Modell überlebte die Oberfläche. Das ist der Preis und wird nicht kleingeredet.
* **Neue FFI-Schicht:** `mpv_create`, `mpv_render_context_create` mit
  `MPV_RENDER_PARAM_OPENGL_INIT_PARAMS`, Render-Callback, `mpv_render_context_render`,
  `eglSwapBuffers`. Plattformabhängig (Wayland-EGL hier, Windows später über WGL/D3D).
* **Fenstergrenzen:** Die `wl_surface` des Tauri-Fensters kommt über
  `raw-window-handle`; darauf eine Subsurface und ein `wl_egl_window`. Ob die WebView
  darunter durchscheint, ist **unbewiesen** und der erste Spike.
* Der bestehende Kern (`mpv.rs`, `plan.rs`) bleibt wertvoll: Argumente, Fähigkeiten,
  Spuren, Position — nur der Transport ändert sich.

## Offene Fragen, die der Spike beantworten muss

1. Kommt man an die `wl_surface` des Tauri-Fensters, und lässt sich darauf eine
   Subsurface mit EGL-Fläche legen?
2. Zeichnet die WebView über einer Subsurface durchsichtig, sodass das Bild sichtbar ist
   (Fenster transparent, Seitenhintergrund transparent)?
3. Hält die Bildrate mit `gpu-next`-Qualität (HDR-Durchreichung, VAAPI) im eigenen
   GL-Kontext?
4. Verträgt sich WebKits eigene GL-Nutzung mit unserem Kontext (zwei Kontexte, ein
   Prozess)?

Fällt 2 oder 3 aus, bleibt als Rückfallebene ein **eigenes natives Fenster** derselben
App — weniger integriert als Jellyfin, aber ohne Prozessgrenze und mit unserer Bedienung.

## Umsetzung in Stufen

1. **Spike 05** — Machbarkeit (Fragen 1–4), Wegwerfcode, Ergebnis dokumentiert.
2. **Render-Schicht** im Kern: `mpv_render` hinter einem Feature, mit Tests, die ohne
   GPU laufen (Parameter-Aufbau, Fehlerpfade).
3. **Shell**: Fenster, Subsurface/Swap, Größenänderung, Lebenszyklus.
4. **Oberfläche**: Bedienleiste über dem Bild, Tastenkürzel, Spurauswahl — auf der
   bestehenden `NativePlaybackView`.
5. **Ablösung** des Prozesspfads, sobald 1–4 stehen; der alte Weg bleibt bis dahin
   funktionsfähig.

## Umsetzung: gemessene Ergebnisse

Der Spike (Fragen 1–4) ist **vollständig beantwortet**, alle vier positiv — die in der ADR
genannte Rückfallebene (eigenes natives Fenster) braucht es nicht.

| Frage | Ergebnis |
|---|---|
| 1 · `wl_surface` des Tauri-Fensters erreichbar | `SPIKE05 surface=… display=… 2800x1800` |
| 2 · Subsurface scheint durch die WebView | magenta über `place_above` sichtbar, danach **durch die Seite** über `place_below` — zweimal vom Nutzer bestätigt |
| 3 · Bildrate im eigenen GL-Kontext | `120 Bilder in 2.00 s = 60.0 fps` gegen Frame-Callbacks |
| 4 · GL-Kontexte von WebKit und libmpv | `120 mpv-Bilder (0 Fehler) … 60.0 fps · Format wrapped_avframe` |

### Fünf Bedingungen, jede gemessen

1. **libmpv-Handle vor `gtk_init()` anlegen.** Danach liefert `mpv_create` NULL — reproduziert
   außerhalb der App. Ein davor angelegtes Handle arbeitet vollständig weiter. In der App
   geschieht das in `run()` vor `tauri::Builder`; `Libmpv::create` nennt die Ursache im Fehlertext.
2. **`MPV_RENDER_PARAM_OPENGL_FBO` bei jedem Render-Aufruf**, auch bei `fbo = 0`. Ohne ihn
   scheitert jeder Frame, während das Video sauber dekodiert — ein Zustand, der wie ein
   Kontextproblem aussieht.
3. **Fenster und Seite durchsichtig, Bild unter der Oberfläche.** Nur während der Wiedergabe:
   eine Klasse am `body` hängt am Wiedergabezustand, sodass die App außerhalb der Wiedergabe
   aussieht wie zuvor.
4. **Wayland-Fenster-Konfiguration liefert GLES2**, kein Desktop-GL. Das Render-Backend ist damit
   vorgezeichnet; ein Desktop-GL-Kontext auf einer Fenster-Konfiguration wird mit `BadConfig`
   beantwortet.
5. **`set_desync()` auf der Kind-Oberfläche**, sonst hängt die Bildrate an den Commits der
   Oberfläche.

### Was auf `main` steht

| Schicht | Ort |
|---|---|
| Optionsfläche (Prozess-Argumente → libmpv-Optionen) | `player/src/libmpv.rs` |
| Handle, Kommandos, Properties, Ereignisse, Spuren | `player/src/libmpv.rs` |
| Render-Kontext (GL-Seite bleibt draußen) | `player/src/libmpv.rs` |
| Videofläche (EGL, Subsurface, Swap, Größe) | `src/render.rs` |
| Wiedergabeweg, zur Kompilierzeit gewählt | `src/commands/playback.rs` |

### Live gemessen gegen den Testserver

```
2. Server antwortet: HTTP 200   direct_play=true   Dauer 6158s  1480x1080
6. Wiedergabe gestartet (im App-Prozess)
   Position: 1.83s / 6158.18s
mpv-Prozesse während der Wiedergabe: 0
```

Fortsetzen: `PLAY_START=120` beginnt mit `Position: 120.00s` und läuft von dort weiter — die
Startposition wird also über `--start` auch im eigenen Prozess angewandt.

Bild im Fenster (Kriterium 2): `NATIVPRUEFUNG 120 Bilder in 3.90 s = 30.8 fps · Größe 2800x1800`
bei `mpv-Prozesse: 0`, vom Nutzer bestätigt. Die 30,8 statt 60 fps sind kein Rückschritt: die
Quelle liefert 30 Bilder/s, der Takt kommt jetzt von mpv statt von der Schleife.

### Bewusst offen

* **Prozessisolation ist verloren.** Ein Absturz in libmpv beendet die App. Das ist der Preis
  für ein Fenster ohne Prozessgrenze und war die Entscheidung dieser ADR, nicht ein Unfall.
* **Windows** hat keinen Renderer (WGL/D3D11); der Prozesspfad ist dort der einzige Weg und
  bleibt als dokumentierte Lücke.
* **HDR** ist über die Optionsfläche übersetzt, aber mit dem neuen Renderer **nicht neu
  gemessen** — `--target-colorspace-hint` und `gpu-next`-Verhalten sind unverändert weitergereicht,
  ein eigener Nachweis steht aus.
