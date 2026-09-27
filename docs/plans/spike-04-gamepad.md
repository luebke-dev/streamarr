# Spike 0.4: Gamepad-Eingabe

Datum: 2026-09-27
Status: abgeschlossen
Bezug: [Desktop-App-Plan](desktop-app.md) Aufgabe 0.4

## Fragestellung

Der Plan verlangt: *„`gilrs` erkennt Xbox/DS4-Pad nativ, Werte kommen im
Datenkanal-Format an"* und *„Hotplug funktioniert"*.

Der Wire-Vertrag war bereits durch `protocol.rs` und die Golden-Tests fixiert.
Gefehlt hat die **Leseseite**: Geräteerkennung, Hot-Plug, Übersetzung physischer
Buttons in die Indizes, die der Server erwartet, und Unterdrückung unveränderter
Achsenwerte.

## Ergebnis

| Prüfung | Ergebnis |
|---|---|
| `gilrs` startet | ✅ |
| Pad wird erkannt | ✅ virtuelles uinput-Pad, `gilrs` liest es als Xbox-360-Pad |
| Layout-Erkennung | ✅ „Microsoft X-Box One pad" → `Standard` |
| Buttons → Wire-Indizes | ✅ A→0, B→1, Y→3, X→2, L1→4, Start→9, Select→8, D-Pad→12–15 |
| Analogsticks | ✅ links (0,0/0,1), rechts (1,0/1,1), Werte korrekt vorzeichenrichtig |
| Trigger | ✅ linkes Trigger-Wert 0,8 → Index 6 (`L2`), beim Loslassen Index 6 false |
| Duplikat-Unterdrückung | ✅ `ButtonChanged` nach `ButtonPressed` erzeugt keine Doppelmeldung |
| Hot-Plug | ✅ Connect → Disconnect → Connect → Disconnect |
| **Hängende Taste beim Abstecken** | ✅ **erkannt und behoben** (siehe unten) |

Live gemessen gegen ein echtes `/dev/uinput`-Gerät, nicht nur gegen die reine
Übersetzungslogik.

## Der wichtigste Befund: hängende Tasten

**Ein Pad, das abgesteckt wird (oder dessen Akku stirbt), während eine Taste
gedrückt ist, kann das Loslassen nicht mehr senden.** Im Spiel bleibt diese
Taste dann **dauerhaft gedrückt** — die Spielfigur läuft endlos weiter.

Reproduziert mit dem `stuck`-Szenario:

```
PAD CONNECTED id=0 name="Xbox 360 Controller"
INPUT  pad=0 {"type":"gamepadbutton","index":0,"pressed":true}   # A gedrückt
                                                                  # ...abgesteckt
```

Ohne Gegenmaßnahme endet die Ausgabe hier: Das Spiel sieht A für immer gedrückt.
Der Client muss die Releases **selbst erzeugen**. Mit der Korrektur:

```
INPUT   pad=0 {"type":"gamepadbutton","index":0,"pressed":true}
RELEASE pad=0 {"type":"gamepadbutton","index":0,"pressed":false}  # synthetisch
PAD DISCONNECTED id=0 name="Xbox 360 Controller"
```

Reihenfolge ist bewusst: **erst die Releases, dann das Disconnect-Ereignis.** Die
Shell wird das Disconnect-Ereignis zum Abbau des Datenkanals nutzen; käme es
zuerst, würden die Releases nie ankommen.

Dabei kam ein **zweiter Fehler** heraus, den erst ein Test zeigte:
`release_all` meldete die Releases, **löschte den internen Zustand aber nicht**.
Nach einem Reconnect hielt der Übersetzer die Taste weiter für gedrückt und
verwarf den ersten echten Tastendruck als Duplikat — ein still verlorener
Tastendruck nach jedem Reconnect.

## Weitere Befunde

**1. Ein Testpad muss originalgetreu sein, sonst misst man Unsinn.** Das erste
virtuelle Pad deklarierte nur `ABS_X/Y/RX/RY`. Die Messung ergab dadurch zwei
scheinbare Fehler: der rechte Stick-X kam invertiert an und rechter Stick-Y löste
einen **Trigger-Button** aus. Beides war ein **Fehler des Testgeräts**: Auf der
Xbox-360-Zuordnung, die `gilrs` verwendet, sind `ABS_Z`/`ABS_RZ` die *Trigger*
(`LeftZ`/`RightZ`), und ohne diese Achsen verschiebt sich die Bedeutung der
übrigen Codes. Ein echtes Pad deklariert alle Achsen. Nach der Korrektur waren
die Werte korrekt — der Fehler lag nie im Client.

**2. Gamepads nutzen absolute Achsen.** `ABS_X`/`ABS_Y`, nicht `REL_X`/`REL_Y`:
Ein Stick hat eine *Position*, kein Delta. Mit relativen Achsen erkennt `gilrs`
das Gerät gar nicht als Gamepad.

**3. `gilrs` normalisiert Rohcodes über eine Gerätedatenbank.** Ein gesendetes
`BTN_SOUTH` (304) kommt als `Button::South` an, und `ABS_Z` als
`Axis::LeftZ` — nicht als das, was auf dem Draht stand. Die Übersetzung darf
deshalb nicht auf Rohcodes aufbauen.

**4. `gilrs` braucht ~1,5 s nach der Geräteerzeugung**, bevor es Events liest.
Ein sofort danach gesendeter Tastendruck geht verloren. Kein Client-Fehler, aber
wichtig für Tests — und ein Hinweis darauf, dass ein Pad nach dem Anstecken nicht
augenblicklich Eingaben liefert.

**5. `gilrs::ev::Code` hat keinen öffentlichen Konstruktor.** Dadurch lässt sich
ein `EventType` in einem Test **nicht** erzeugen. Die Kernlogik wurde deshalb von
`gilrs`-Typen entkoppelt: `PadInput` ist ein eigener Typ in Browser-Konventionen,
`axis_input`/`standard_button` adaptieren, und `PadTranslator::apply` ist rein und
testbar. Ohne diese Trennung wäre ausgerechnet der Layout-Swap — der bei Fehlern
zwei Face-Buttons vertauscht — untestbar gewesen.

## Bekannte Lücke: Layout-Erkennung ist eine Namensheuristik

Der Browser kann das Gerät fragen (`pad.mapping === 'standard'`). **`gilrs` kann
das nicht** — es gibt keine Entsprechung. Die Erkennung ist deshalb eine
Allow-Liste bekannter Namen:

```rust
const STANDARD: [&str; 10] = ["x-box", "xbox", "dualshock", "dualsense",
    "playstation", "8bitdo", "stadia", "switch pro", "pro controller", "gamesir"];
```

Alles Unbekannte bekommt den Swap (Nicht-Standard), weil das der sichere Fehler
ist. **Das ist die eine Stelle, an der der native Client nicht so präzise sein
kann wie der Web-Client.** Ein unbekanntes Pad mit Standard-Layout bekäme A/B und
X/Y vertauscht. Abhilfe in Phase 3: manuelle Layout-Umschaltung in den
Einstellungen, plus Test mit realer Hardware.

## Umgebungsabhängigkeiten

- `gilrs` 0.11 (braucht `libudev` auf Linux) → deshalb Feature `gamepad`
- `evdev` 0.13 → **nur** für das Testwerkzeug `virtual-pad`
- `/dev/uinput` muss schreibbar sein (hier: über eine ACL für den Nutzer)

**Container-Einschränkung:** Der Test muss auf dem **Host** laufen. Ein Container
hat ein eigenes `/dev` (devtmpfs), und neu erzeugte Geräte erscheinen dort nicht;
`/dev` ist zudem read-only, sodass sich die Nodes nicht nachreichen lassen. Für
CI heißt das: Gamepad-Tests brauchen entweder einen Host-Runner oder
`--device /dev/input` plus einen Weg, Geräte nachzureichen.

## Grenzen

1. **Kein physisches Pad getestet.** Alle Messungen liefen gegen ein virtuelles
   uinput-Gerät. Das deckt Erkennung, Hot-Plug und Übersetzung ab, aber nicht die
   Eigenheiten echter Hardware (Achsen-Rauschen, Dead-Zones, Funk-Aussetzer).
2. **Nur ein Pad gleichzeitig** geprüft. Mehrspieler ist im Code vorgesehen
   (`PadTranslator` pro Pad) und durch einen Test auf getrennten Zustand
   abgedeckt, aber nicht live gemessen.
3. **Force Feedback nicht geprüft** (nicht Teil der Aufgabe).
4. **Vibration/Rumble** wird nicht an den Server gesendet; der Wire-Vertrag sieht
   es nicht vor.
5. **Windows nicht gemessen.** `gilrs` unterstützt es (WGI/XInput), der Code ist
   plattformneutral — aber ungeprüft.

## Ergebnis

| Frage aus 0.4 | Antwort |
|---|---|
| `gilrs` erkennt ein Pad nativ | ✅ |
| Werte kommen im Datenkanal-Format an | ✅ 12/11/6 Nachrichten in drei Szenarien |
| Hot-Plug funktioniert | ✅ inkl. Erkennung und Neuverbindung |
| Zusätzlich gefunden | hängende Tasten beim Abstecken — **behoben** |
