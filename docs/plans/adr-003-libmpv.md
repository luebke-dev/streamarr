# ADR 003 — Medienwiedergabe über libmpv im App-Prozess

**Status:** entschieden (2026-10-22)
**Ersetzt teilweise:** ADR 001, soweit es den getrennten mpv-Prozess betrifft

## Kontext

Die App startet mpv heute als **eigenen Prozess** und steuert ihn über JSON-IPC
(`desktop/player/src/mpv.rs`). Das Video erscheint in einem **eigenen Vollbild-Fenster**,
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
