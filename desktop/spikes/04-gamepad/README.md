# Spike 0.4 — Gamepad-Messprogramm

Reproduktion der Messung aus [spike-04-gamepad.md](../../../docs/plans/spike-04-gamepad.md).

Es gibt hier kein physisches Gamepad. Statt die Leseseite ungetestet zu lassen,
erzeugt `virtual-pad` über `/dev/uinput` ein **echtes Eingabegerät**, das Kernel
und udev wie Hardware behandeln. `gilrs` kann den Unterschied nicht erkennen —
alles ab der Geräteerkennung ist damit wirklich geprüft.

## Voraussetzungen

```bash
distrobox enter tauri44
sudo dnf install -y systemd-devel          # libudev für gilrs
test -w /dev/uinput && echo "uinput schreibbar"
```

**Auf dem Host ausführen, nicht im Container.** Ein Container hat ein eigenes
`/dev` (devtmpfs); dort erzeugte Geräte erscheinen nicht, und `/dev` ist
read-only, sodass sich Nodes nicht nachreichen lassen.

```bash
cd desktop/player
cargo build --release --features gamepad
```

## Lauf

Zwei Prozesse: der Leser und das virtuelle Pad.

```bash
P=target/release

# Szenarien des Lesers: press | axes | hotplug | stuck
$P/spike-gamepad 16 &                      # liest 16 Sekunden
sleep 2                                    # gilrs braucht ~1,5s nach Geraeteerstellung
$P/virtual-pad press
wait
```

`SPIKE_TRACE=1` zeigt zusätzlich jede **Rohlesung** neben der Übersetzung:

```
RAW pad=0 ButtonPressed(South, Code(...)) -> Some(Button { button: A, pressed: true })
INPUT pad=0 {"type":"gamepadbutton","index":0,"pressed":true}
```

Damit wurden sowohl die Achsen-Anomalie (Testgerät, nicht Client) als auch die
fehlenden Events gefunden.

## Die Szenarien und was sie prüfen

| Szenario | Prüft |
|---|---|
| `press` | Alle Buttons erreichen den richtigen Wire-Index |
| `axes` | Sticks (vorzeichenrichtig), Trigger, D-Pad; Duplikat-Unterdrückung |
| `hotplug` | Erkennung, Abstecken, Neuverbindung |
| `stuck` | **Hängende Taste**: Abstecken mit gedrückter Taste |

## `stuck` — der wichtigste Test

Ein Pad, das während eines Tastendrucks abgesteckt wird, kann das Loslassen nicht
mehr senden. Ohne Gegenmaßnahme bleibt die Taste im Spiel **für immer** gedrückt.

Erwartet (mit Korrektur):

```
INPUT   pad=0 {"type":"gamepadbutton","index":0,"pressed":true}
RELEASE pad=0 {"type":"gamepadbutton","index":0,"pressed":false}
PAD DISCONNECTED id=0 name="Xbox 360 Controller"
```

Die Reihenfolge ist Teil des Vertrags: **Releases vor dem Disconnect**, weil die
Shell beim Disconnect den Datenkanal abbaut.

## Ein originalgetreues Testpad ist Pflicht

Ein Pad, das nur `ABS_X/Y/RX/RY` deklariert, misst nicht, was ein echtes Pad
meldet. Auf der Xbox-360-Zuordnung, die `gilrs` verwendet, sind `ABS_Z`/`ABS_RZ`
die **Trigger**; fehlen sie, verschiebt sich die Bedeutung der übrigen Codes, und
der rechte Stick schlägt scheinbar als Trigger-Button durch. `build_pad`
deklariert deshalb alle Achsen eines echten Controllers.

Ebenfalls wichtig: Gamepads nutzen **absolute** Achsen (`ABS_*`), nicht relative
(`REL_*`). Mit `REL_X` erkennt `gilrs` das Gerät nicht als Gamepad.

## Der Namensparameter

```bash
$P/virtual-pad press "Generic USB Joystick"    # Nicht-Standard-Layout
```

Der Gerätename steuert die Layout-Erkennung (`layout_for`). Mit einem unbekannten
Namen lässt sich der Swap-Pfad gegen ein Gerät prüfen, das Standard-Codes sendet —
nützlich, weil `gilrs` das `mapping`-Feld des Browsers nicht kennt und die
Erkennung deshalb eine Namensheuristik ist (siehe Spike-Doku).
