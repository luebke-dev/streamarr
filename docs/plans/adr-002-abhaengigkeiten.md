# ADR 002 — mpv und GStreamer: System oder gebündelt?

**Status:** entschieden (Aufgabe 4.2 des Plans)
**Datum:** 2026-09
**Betrifft:** `.deb`, `.rpm`, AppImage, Windows-Installer

## Kontext

Die Desktop-App spielt Medien (über mpv) und Spiele (über GStreamer) ab. Beide
sind in dieser Umgebung **vorhanden**, aber nicht Teil der App:

* **mpv** läuft als **eigener Prozess** und wird über sein JSON-IPC gesteuert
  (Entscheidung §9.2 des Plans, in Spike 0.3 belegt) — die App linkt libmpv
  nicht.
* **GStreamer** wird für Spiele **gelinkt**, aber nur, wenn das Cargo-Feature
  `spike` aktiv ist. Gemessen am Release-Binary: `objdump -p Streamarr | grep -c gst`
  ergibt **0**. Das Feature ist in der Shell derzeit **nicht** aktiv, weil die
  Spiel-Pipeline dort noch nicht verdrahtet ist (siehe „Offen" unten).

Damit stellt sich die Frage für beide: mitliefern oder vom System erwarten?

## Gemessene Fakten

| | mpv 0.41.0 | GStreamer 1.28.7 |
|---|---|---|
| Lizenz | `GPL-2.0-or-later AND LGPL-2.1-or-later AND BSD-2-Clause AND BSD-3-Clause AND ISC AND MIT` | `LGPL-2.1-or-later` |
| Größe | ca. 3 MB Binärdatei, dazu Dutzende Codec-Bibliotheken | Kern ca. 5 MB, dazu die Plugin-Pakete |
| Einbindung | eigener Prozess, IPC über Unix-Socket | gelinkt (Feature `spike`) |

Die für Spiele nötigen Elemente und ihre Plugins (gemessen mit
`gst-inspect-1.0`):

```
webrtcbin          libgstwebrtc.so            gstreamer1-plugins-bad-free
rtpjitterbuffer    libgstrtpmanager.so        gstreamer1-plugins-good
rtph264depay       libgstrtp.so               gstreamer1-plugins-good
h264parse          libgstvideoparsersbad.so   gstreamer1-plugins-bad-free
waylandsink        libgstwaylandsink.so       gstreamer1-plugins-bad-free
vah264dec          libgstva.so                gstreamer1-vaapi (AMD)
avdec_h264         libgstlibav.so             gstreamer1-plugins-libav
```

Sieben Plugins aus fünf Paketen, und **welche** nötig sind, hängt von der
Hardware ab: `vah264dec` gibt es nur auf AMD, `nvh264dec` nur auf NVIDIA,
`d3d11videosink` nur auf Windows.

## Entscheidung

**Beide werden vom System erwartet — nicht gebündelt.**

1. **mpv bleibt ein externer Prozess.** Das ist bereits die Architekturentscheidung
   (§9.2) und wird hier nur bestätigt: die App linkt libmpv nicht, also gibt es
   nichts zu bündeln. Der Preis steht im Plan und ist gemessen: etwa 100 ms
   Prozessstart.
2. **GStreamer bleibt eine Systemabhängigkeit.** Für `.deb` und `.rpm` wird sie
   deklariert (`gstreamer1`, `gstreamer1-plugins-base`, `gstreamer1-plugins-good`
   und bei Bedarf `-bad-free`, `-libav`, `gstreamer1-vaapi`).
3. **Der AppImage ist die dokumentierte Ausnahme.** Er wird auf einem System ohne
   installierte Plugins **keine Spiele abspielen** können. Das ist eine bewusste
   Einschränkung, keine Lücke: ihn vollständig zu bündeln hieße, fünf Plugin-Pakete
   samt Codec-Bibliotheken mitzuschleppen, die Größe zu vervielfachen und die
   Lizenzlage zu verkomplizieren — für ein Paket, dessen Zweck „läuft ohne
   Installation" ist und nicht „läuft ohne Abhängigkeiten".

## Begründung im Einzelnen

### Warum nicht bündeln

* **Die Hardwareabhängigkeit lässt sich nicht mitbündeln.** Die
  Dekoder-Kette wird zur Laufzeit gewählt (`game_pipeline::DecodePlan`), weil
  `vaapidecodebin` auf dieser Maschine fehlt und `nvh264dec` auf einer anderen.
  Ein Bündel müsste alle Varianten enthalten — also mehrere hundert MB, von denen
  jede Maschine den größten Teil nie benutzt.
* **Lizenzlage.** GStreamer ist LGPL-2.1 — Bündelung ist erlaubt, verlangt aber,
  dass Nutzer die Bibliothek ersetzen können. Bei einem AppImage, das ein
  SquashFS-Abbild ist, ist das praktisch nicht erfüllbar; bei `.deb`/`.rpm` löst
  die Systemabhängigkeit genau dieses Problem.
* **Distributionen wollen ihre eigenen Bibliotheken.** Ein `.deb`, das eine
  eigene libavcodec mitbringt, ist auf Debian ein bekannter Grund für
  Sicherheitslücken: die mitgelieferte Kopie bekommt die Aktualisierungen nicht.
* **Der Aktualisierungspfad.** GStreamer-Sicherheitsupdates kommen über den
  Paketmanager. Eine gebündelte Kopie müsste die App selbst nachziehen, und die
  Update-Prüfung tut das nicht (sie prüft die App-Version, nicht die einer
  Bibliothek).

### Warum die AppImage-Ausnahme vertretbar ist

Sie ist **dokumentiert und überprüfbar**: Der Nutzer erfährt in der Anleitung,
dass Spiele im AppImage die System-Plugins brauchen, und die App meldet einen
fehlenden Dekoder namentlich (`BranchError::MissingElement` nennt Element und
Paketvorschlag), statt ein schwarzes Bild zu zeigen.

## Konsequenzen

1. `desktop/scripts/check_bundle_deps.sh` prüft, dass die Pakete jede **direkt
   gelinkte** Bibliothek deklarieren. GStreamer erscheint dort erst, wenn die
   Shell das `spike`-Feature aktiviert — dann **muss** die Liste mitwachsen, und
   das Skript schlägt fehl, wenn sie es nicht tut.
2. Die GStreamer-Plugin-Pakete sind **Laufzeit-, nicht Link-Abhängigkeiten**: sie
   werden über `dlopen` geladen und erscheinen deshalb nicht in `DT_NEEDED`. Das
   Skript kann sie also nicht finden. Sie werden in der Anleitung genannt, und
   die App nennt das fehlende Element zur Laufzeit beim Namen.
3. `mpv` wird als **Empfehlung** deklariert, nicht als harte Abhängigkeit —
   umgesetzt als `bundle.linux.deb.recommends` und `…rpm.recommends`, beide
   geprüft (`dpkg-deb -f … Recommends` → `mpv`). Eine harte Abhängigkeit wäre
   falsch: die App **startet** ohne mpv, sie kann nur nichts abspielen. Und sie
   sagt es: `MpvError::NotInstalled` wird aus `ErrorKind::NotFound` beim
   Prozessstart gebildet, ist also eine benannte Fehlerart und kein
   allgemeiner Absturz.

   Für das fehlende GStreamer-Element gilt dasselbe Prinzip zur Laufzeit:
   `BranchError::MissingElement` nennt Element und Paketvorschlag, statt ein
   schwarzes Bild zu zeigen. Genau deshalb ist die Bündelung verzichtbar: der
   Nutzer erfährt, was fehlt.

## Offen

Die Spiel-Pipeline ist in `desktop/player` implementiert und live belegt
(`waylandsink`, `DECODED=10`, `INPUT_SENT=6 INPUT_RECEIVED=6`), aber **noch nicht
in der Shell verdrahtet**: dort ist nur das Feature `gamepad` aktiv. Solange das
so ist, braucht der **ausgelieferte** Build GStreamer nicht — und die
Paketabhängigkeiten sind entsprechend leer. Sobald die Verdrahtung erfolgt, sind
die Plugin-Pakete zu ergänzen und `check_bundle_deps.sh` wird das Einbinden der
GStreamer-Bibliotheken erzwingen.
