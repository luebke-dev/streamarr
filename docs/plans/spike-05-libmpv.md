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

## Stand der Umsetzung

**Increment 1 (erledigt, gemessen).** Die App liest ihre eigenen Handles:

```
SPIKE05 surface=0x562ebdfec9e0 display=0x562ebdcf9800 2800x1800
```

`read_handles` ist über `HasWindowHandle + HasDisplayHandle` verallgemeinert, weil das
Fenster ein `WebviewWindow` ist und nicht `Window` — der erste Entwurf nahm `&Window`, der
Compiler hat es korrigiert.

**Increment 2 (erledigt, gemessen).** Übernahme der bestehenden Verbindung:

```
SPIKE05 Verbindung übernommen, Oberfläche als Proxy griff
```

Zwei Aufrufe, die sich als richtig erwiesen haben:

```rust
let backend = unsafe {
    wayland_backend::sys::client::Backend::from_foreign_display(display_ptr)
};                      // Guest-Modus: schließt die Verbindung beim Drop NICHT
let connection = wayland_client::Connection::from_backend(backend);
let id = unsafe { ObjectId::from_ptr(WlSurface::interface(), surface_ptr) }?;
let proxy = WlSurface::from_id(&connection, id)?;
```

Zwei Annahmen waren falsch und kosteten je einen Compilerlauf: `WlSurface` liegt unter
`wayland_client::protocol::wl_surface`, und `ObjectId::from_ptr` liefert ein `Result`.

**Increment 3 (erledigt, gemessen).** Die Frage, um die es geht:

1. `registry_queue_init::<State>(&connection)` — braucht eine `Dispatch`-Implementierung für
   `WlRegistry` und danach für `WlCompositor`, `WlSubcompositor`, `WlShm`. Das ist
   Boilerplate; `wayland_client::delegate_noop!` ist der vorgesehene Weg und noch nicht
   ausprobiert.
2. Globals binden, Kind-Oberfläche erzeugen:
   `compositor.create_surface(&qh, ())` → `subcompositor.get_subsurface(&child, &parent, &qh, ())`
   → `set_position(0, 0)` und **zuerst `place_above`** (siehe unten).
3. `wl_shm`-Pool mit einem magenta gefüllten Puffer, `attach`, `damage_buffer`, `commit`,
   `connection.flush()`.

**Warum zuerst `place_above`:** Damit lässt sich die Infrastruktur (Subsurface, Puffer,
Commit) ohne jede Konfigurationsänderung prüfen — deckt Magenta die Oberfläche ab, steht das
Fundament. Erst danach kommt `place_below` **zusammen mit** `transparent: true` im Fenster
und durchsichtigem Seitenhintergrund; das ist die eigentliche Frage 2 und ändert die
App-Konfiguration, also wird sie bewusst als letzter Teilschritt gemacht.

### Ergebnis zu Frage (b) — Durchscheinen: **belegt**

Der Test lief in zwei Stufen, und die Reihenfolge war die eigentliche Absicherung:

1. **`place_above`** — ein magenta `wl_shm`-Patch von 400×300 oben links, **ohne jede
   Konfigurationsänderung**. Vom Nutzer bestätigt: Rechteck sichtbar. Damit war bewiesen,
   dass Kind-Oberfläche, Puffer, Commit und Stapelung auf dem echten Fenster funktionieren —
   unabhängig von der Transparenzfrage.
2. **`place_below`** plus durchsichtiges Fenster (`transparent: true`,
   `backgroundColor: "#00000000"`) plus vorübergehende CSS-Regel, die `body` und `#q-app`
   durchsichtig macht. Vom Nutzer bestätigt: Magenta schimmert **durch die Seite** hindurch.

Log des entscheidenden Laufs:

```
SPIKE05 Verbindung übernommen, Oberfläche als Proxy griff
SPIKE05 Globals: compositor, subcompositor und shm gebunden
SPIKE05 magenta Patch 400x300 unter der WebView gesetzt
```

Beide Stufen zusammen sind wichtig: Stufe 1 schließt aus, dass ein Ausbleiben in Stufe 2 an
der Subsurface liegt; Stufe 2 trennt „Transparenz greift nicht" von „Stapelung scheitert".

### Folge für ADR 003, die aus dem Ergebnis folgt

Weil die Videofläche **unter** der Seite liegt, muss das gesamte Fenster alpha-blended sein:
`transparent: true` und eine Oberfläche, die dort, wo Bild liegen soll, nichts Undurchsichtiges
malt. Das ist keine Spike-Eigenheit, sondern eine Eigenschaft des Zielaufbaus und gehört in
die Konsequenzen der ADR — samt der Kosten (jede Fensterfläche wird gemischt) und der Regel,
dass die Bedienleiste über dem Bild liegt statt daneben.

Die drei Änderungen (Fenster-transparent, Seitenhintergrund, `place_below`) liegen bewusst
nur auf dem Spike-Branch. Ein durchsichtiges Fenster ist kein Produktzustand, solange die
Wiedergabe nicht wirklich darin rendert.
