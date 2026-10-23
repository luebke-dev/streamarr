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

### Ergebnis zu Frage (c)/(d), erste Hälfte: eigener GL-Kontext — **belegt**

Ein EGL-Kontext auf dem **übernommenen** `wl_display`, angelegt während WebKit läuft und
komponiert:

```
SPIKE05 EGL Mesa Project · GL 4.6 (Compatibility Profile) Mesa 26.2.3 ·
         AMD Radeon 8060S Graphics (radeonsi, strix_halo, ACO, DRM …)
```

Damit ist die Voraussetzung für die mpv-Render-API erfüllt: sie zeichnet durch **unseren**
Kontext und braucht dessen `get_proc_address`. Ein Pbuffer genügt für diese Teilfrage — kein
`wl_egl_window`, keine Swap-Schleife; fällt hier etwas aus, liegt es an EGL und nicht an der
Präsentation.

Zwei Messungen waren nötig, und beide waren lehrreich:

* `get_platform_display` antwortet auf Surface-Attribute (`SURFACE_TYPE`, `PBUFFER_BIT`, …)
  mit **`BadAttribute`**. Diese Attribute gehören in `choose_first_config`; die
  Plattformliste enthält nur den Terminator.
* Die Attributlisten sind **unterschiedlich typisiert**: `get_platform_display` nimmt
  `&[Attrib]` (= `usize`), `choose_first_config`, `create_context` und
  `create_pbuffer_surface` nehmen `&[i32]`. Ein einheitlicher Cast ist deshalb falsch.

Noch offen in (c): eine Swap-Schleife in die Kind-Oberfläche mit gemessener Bildrate — dafür
kommt `wayland-egl` (`wl_egl_window`) dazu. Und in (d) der eigentliche Nachweis: libmpv
zeichnet durch diesen Kontext, während WebKit weiterkomponiert.

### Ergebnis zu Frage (c) — Bildrate: **belegt**

Eine Swap-Schleife mit **eigenem** EGL-Kontext in die Kind-Oberfläche unter der WebView,
getaktet über Wayland-**Frame-Callbacks**:

```
SPIKE05 Bildrate: 120 Bilder in 2.00 s = 60.0 fps (mit Frame-Callbacks)
```

Die Frame-Callbacks sind der Punkt: `swap_buffers` kehrt sofort zurück, ein Zählen der
Aufrufe misst also nur, wie schnell die CPU Puffer einreicht. Erst das Warten auf den
Callback misst, was das Display zeigt — und das sind hier exakt 60 Hz.

Drei Messungen waren nötig, jede mit einer Lehre:

* **Erst hing die Schleife.** Beim `setup` ist die Oberfläche noch nicht gemappt, also kommt
  kein Frame-Callback und `roundtrip` blockiert für immer. Der Lauf gehört in einen Thread
  und braucht Anlaufzeit sowie ein paar Swaps ohne Warten, damit Puffer hängen.
* **`BadMatch`** bei `EGL_CONTEXT_MAJOR/MINOR_VERSION` 1.5 und einer Fenster-Konfiguration.
* **`BadConfig`** bei einem GL-Kontext ohne Versionsangabe, obwohl die Konfiguration
  einwandfrei aussieht: `SURFACE_TYPE=0x5` (Puffer+Window), `RENDERABLE_TYPE=0x4c` (GL und
  ES), `CONFIG_CAVEAT=0x3038` (kein Caveat). Ein **ES2**-Kontext auf derselben Konfiguration
  geht sofort.

**Das ist eine Randbedingung für den Umbau, keine Fußnote:** mit einer Wayland-Fenster-
Konfiguration bekommt man auf diesem Treiber einen **GLES2**-Kontext, keinen Desktop-GL-
Kontext. Die mpv-Render-API (`MPV_RENDER_API_TYPE_OPENGL`) läuft auf GLES2 — der Weg ist
also gangbar, aber die Wahl des Render-Backends ist damit vorgezeichnet. Der GL-4.6-Kontext
aus der Pbuffer-Messung bleibt für einen Offscreen-Pfad verfügbar.

Nebenbei: die Kind-Oberfläche steht auf `set_desync()`, damit das Bild nicht auf die
Commits der Oberfläche wartet — ohne das hängt die Bildrate an der WebView.

### Ergebnis zu Frage (d) — libmpv im App-Prozess: **belegt, mit zwei Bedingungen**

Der Versuch, libmpv durch unseren Kontext zeichnen zu lassen, ist nicht bis zur ersten
Bildausgabe gekommen. Was gemessen ist, ist dafür eindeutig:

| Ort im Programm | Ergebnis |
|---|---|
| `run()` ganz am Anfang, vor Tauri | `mpv_create = 0x5599d764a670` — **funktioniert** |
| `setup`, nach Tauri-Initialisierung | `mpv_create = 0x0` — **scheitert** |
| API-Version im App-Prozess | `131077` — die Bindung ist korrekt |
| Minimalprogramm in Rust, gleiche Bindung, gleicher Container | Handle gesetzt, `initialize: 0` |
| C-Programm mit `pkg-config mpv`, auch ohne Terminal | Handle gesetzt, `initialize: 0` |

Damit ist ausgeschlossen: falsche Symbolbindung (API-Version stimmt), fehlende Bibliothek
(das Binary bindet `libmpv.so.2`, der Host-`ldd` meldet „not found", weil es auf dem Host
kein libmpv gibt — im Container läuft es), Umgebungsproblem von `HOME`, und fehlendes
Terminal. Übrig bleibt: **zwischen Prozessanfang und `setup` geht libmpv in diesem Prozess
kaputt.**

Das ist kein Nebenbefund. Die ADR 003 setzt „libmpv im App-Prozess" voraus; wenn libmpv dort
nicht initialisierbar ist, trägt der ganze Weg nicht. Die Ursache ist noch nicht eingekreist —
in Frage kommen die GTK/WebKit-Initialisierung in `builder.build()` oder das Setup eines der
Tauri-Plugins (Single-Instance, Deeplink, Updater), die vor dem App-`setup` laufen.

**Nächste Messung, bewusst klein:** je eine Sonde (a) direkt nach `tauri::Builder::default()`,
(b) nach `builder.build(context)` und vor `.run()`, (c) mit vorübergehend abgeschalteten
Plugins. Das trennt Builder, Plugins und WebView-Erzeugung als Ursache. Erst danach lässt sich
sagen, ob der Weg mit einer Anpassung trägt oder ob hier die Alternative vorzulegen ist.

Eine Sonde (`probe_mpv_create`) und ihre zwei Aufrufstellen liegen dafür schon im Code.

#### Auflösung des blockierenden Befunds

Die Ursache war nicht Tauri, sondern **GTK**: `gtk_init()` selbst macht `mpv_create`
unbrauchbar. Reproduziert außerhalb der App, in einem Minimalprogramm:

```
vor gtk_init:  mpv_create = 0x5639c0c404a0   (initialize = 0)
nach gtk_init: mpv_create = 0x0
```

Ein **vor** `gtk_init()` angelegtes Handle funktioniert danach vollständig — es
initialisiert, lädt und dekodiert:

```
handle vor gtk_init: 0x561c738584a0
mpv_initialize nach GTK: 0   loadfile: 0
video-format: wrapped_avframe
```

Damit ist es eine Frage der **Reihenfolge**, nicht der Verträglichkeit. In der App legt
`run()` das Handle vor `tauri::Builder` an; alles Spätere benutzt es weiter.

#### Der Beweis

```
SPIKE05 vor-gtk: mpv_create = 0x55c6056f1670 (vor GTK angelegt)
SPIKE05 libmpv: 120 mpv-Bilder (0 Fehler) in 2.00 s = 60.0 fps · Format wrapped_avframe
```

Vom Nutzer bestätigt: das Testbild ist im App-Fenster zu sehen. libmpv rendert also im
App-Prozess, durch unseren EGL-Kontext, in die Subsurface unter der WebView, während WebKit
weiterkomponiert.

**Zweite Bedingung:** `mpv_render_context_render` braucht `MPV_RENDER_PARAM_OPENGL_FBO` auch
dann, wenn ins Standard-Framebuffer gezeichnet wird (`fbo = 0`). Ohne den Parameter scheitert
**jeder** Frame — der erste Lauf lieferte 0 von 120 Bildern bei erfolgreich dekodiertem Video,
was ohne diese Kenntnis nach einem Kontextproblem ausgesehen hätte.

### Zusammenfassung des Spikes

| Frage | Ergebnis |
|---|---|
| (a) `wl_surface` des Fensters erreichbar | belegt — `surface=… display=… 2800x1800` |
| (b) Subsurface scheint durch die WebView | belegt — zweistufig, vom Nutzer bestätigt |
| (c) Bildrate mit eigenem GL-Kontext | belegt — 60,0 fps gegen Frame-Callbacks |
| (d) GL-Kontexte von WebKit und libmpv | belegt — 120 mpv-Bilder, 0 Fehler, Nutzer sieht das Bild |

**Bedingungen für den Umbau**, alle gemessen:

1. libmpv-Handle **vor** `gtk_init()` anlegen (also in `run()`, vor `tauri::Builder`).
2. `MPV_RENDER_PARAM_OPENGL_FBO` bei jedem Render-Aufruf mitgeben.
3. Fenster und Seite durchsichtig; das Bild liegt **unter** der Oberfläche, die Bedienleiste
   darüber.
4. Wayland-Fenster-Konfiguration liefert **GLES2**, kein Desktop-GL — das Render-Backend ist
   damit vorgezeichnet.
5. Die Kind-Oberfläche auf `set_desync()`, sonst hängt die Bildrate an der WebView.
