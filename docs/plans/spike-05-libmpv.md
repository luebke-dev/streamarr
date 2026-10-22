# Spike 05 — libmpv im App-Prozess, Bild unter der WebView

**Ziel:** die vier Fragen aus ADR 003 beantworten, bevor irgendetwas umgebaut wird.
**Stand:** Voraussetzungen geprüft, Technik festgelegt, Probe noch nicht gebaut.

## Die vier Fragen

1. Kommt man im laufenden Programm an die `wl_surface` des App-Fensters?
2. Scheint eine Subsurface **unter** der WebView durch, wenn das Fenster transparent ist?
3. Ist die Bildrate mit eigenem GL-Kontext brauchbar (inklusive `gpu-next`/HDR)?
4. Vertragen sich WebKits GL-Kontext und unserer im selben Prozess?

Fällt **2** oder **3** aus, wird angehalten und dem Nutzer die Alternative vorgelegt
(eigenes natives Fenster derselben App) — so steht es in ADR 003.

## Geprüfte Voraussetzungen

| Prüfung | Ergebnis | Wie geprüft |
|---|---|---|
| Fenster-Handle erreichbar | **ja** | `tauri 2.12.0` implementiert `HasWindowHandle` für `Window` und `WebviewWindow`; im Quelltext der Kiste nachgesehen |
| Wayland-Verbindung übernehmbar | **ja** | `wayland_backend::sys::client::Backend::from_foreign_display(*mut wl_display)` — laut Dokumentation genau für „plug itself into an existing Wayland connection" gedacht, im Guest-Modus, schließt die Verbindung nicht |
| libmpv | **ja** | `pkg-config --modversion mpv` → 2.5.0, `/usr/lib64/libmpv.so`, Header vorhanden |
| EGL / Wayland-EGL | **ja** | EGL 1.5, `wayland-egl` vorhanden, 66 DRI-Treiber (AMD) |
| `--wid` als Abkürzung | **nein** | mpv bettet nur in X11/Win32/Cocoa ein; Upstream-Issues #1242, #9654 nennen Wayland-Einbetten unmöglich |

## Vorgehen

Der Spike läuft **in der App**, nicht als eigenes Programm — die Frage handelt von genau
diesem Fenster. Er kommt hinter ein Feature `spike-render`, das nie in ein Paket geht.

**Schritt 1 (entscheidet Frage 2, ohne mpv):** Aus dem Fenster-Handle die `wl_surface`
nehmen, mit `Backend::from_foreign_display` die Verbindung übernehmen, `wl_compositor` und
`wl_subcompositor` binden, eine Kind-Oberfläche erzeugen, `place_below(parent, child)`,
einen `wl_shm`-Puffer in Magenta anhängen und committen. Fenster und Seite transparent
machen. **Sieht man Magenta, ist der Weg frei.** Kein GL, kein libmpv — die kleinste
mögliche Probe für die teuerste Unbekannte.

**Schritt 2 (Frage 1 und 4):** `wl_egl_window` auf der Kind-Oberfläche, EGL-Kontext,
`glClear` in einer Schleife, `eglSwapBuffers`. Läuft das neben WebKit stabil, ist die
Kontext-Frage beantwortet.

**Schritt 3 (Frage 3):** libmpv mit `vo=libmpv`, Render-Kontext über
`MPV_RENDER_PARAM_OPENGL_INIT_PARAMS` auf denselben EGL-Kontext, ein Testmedium aus dem
Server abspielen, Bildrate und HDR-Metadaten messen (`--target-colorspace-hint`).

## Was der Spike ausdrücklich nicht tut

Keine Tests, keine Fehlerbehandlung für Produktionsbetrieb, kein Windows, keine
Bedienleiste. Er wird nach der Antwort verworfen oder in die Render-Schicht überführt.

## Neue Abhängigkeiten (nur hinter dem Feature)

- `raw-window-handle` (liegt bereits im Baum)
- `wayland-client` + `wayland-backend` mit `client_system` (übernimmt die bestehende Verbindung)
- `khronos-egl` (dynamisch geladen)
- `libmpv`-Bindings: rohe `extern "C"`-Deklarationen gegen `libmpv.so` oder `libmpv-sys`

Diese Liste ist der Punkt, an dem ADR 002 (Abhängigkeiten) fortgeschrieben werden muss,
sobald der Spike etwas beweist.
