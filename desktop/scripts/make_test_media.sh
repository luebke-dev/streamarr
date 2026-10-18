#!/usr/bin/env bash
# Erzeugt die Testmedien für die mpv-Integrationstests.
#
# Warum ein Skript und keine committeten Dateien: die Medien sind zusammen ~19 MB
# und für die Tests völlig uninteressant — sie müssen nur dekodierbar sein und
# bestimmte Spuren mitbringen. Ein Skript hält das Repo klein und macht sichtbar,
# wovon die Tests ausgehen.
#
# Ausführen:
#   ./desktop/scripts/make_test_media.sh [ZIELVERZEICHNIS]
#
# Standardziel ist /tmp/mpvt, weil genau dort die Tests suchen
# (desktop/player/tests/mpv_integration.rs).

set -euo pipefail

TARGET="${1:-/tmp/mpvt}"
mkdir -p "$TARGET"

if ! command -v ffmpeg >/dev/null 2>&1; then
    echo "Fehler: ffmpeg wird gebraucht, ist aber nicht installiert." >&2
    exit 1
fi

# test.mkv: was die meisten Tests brauchen.
#
#   * H.264 — das Format, das der Server laut lightrays/src/encoder.rs immer wählt
#   * ZWEI Audiospuren in verschiedenen Sprachen (eng/ger), damit der
#     Sprachwechsel und die Spurauswahl überhaupt prüfbar sind. Die deutsche Spur
#     trägt bewusst die bibliografische Form `ger` statt `de`, weil die
#     Zuordnungstabelle genau dafür existiert und echte Dateien beide Formen nutzen.
#   * kurze Laufzeit (10 s): die Tests warten auf Ereignisse, eine lange Datei
#     würde die Suite nur verlangsamen.
#   * testsrc2 statt testsrc: enthält bewegte Strukturen, sodass h264 echte
#     Inter-Frame-Vorhersage betreibt statt eines Standbilds.
echo "→ $TARGET/test.mkv"
ffmpeg -y -v error \
    -f lavfi -i "testsrc2=size=640x360:rate=25:duration=10" \
    -f lavfi -i "sine=frequency=440:duration=10" \
    -f lavfi -i "sine=frequency=880:duration=10" \
    -map 0:v -map 1:a -map 2:a \
    -c:v libx264 -preset ultrafast -pix_fmt yuv420p \
    -c:a ac3 -b:a 128k \
    -metadata:s:a:0 language=eng -metadata:s:a:0 title="English" \
    -metadata:s:a:1 language=ger -metadata:s:a:1 title="Deutsch" \
    -disposition:a:0 default -disposition:a:1 0 \
    "$TARGET/test.mkv"

# sub.mkv: zusätzlich eine eingebettete Untertitelspur, damit die Untertitel-
# pfade der UI prüfbar sind.
echo "→ $TARGET/sub.mkv"
ffmpeg -y -v error \
    -f lavfi -i "testsrc2=size=640x360:rate=25:duration=10" \
    -f lavfi -i "sine=frequency=440:duration=10" \
    -map 0:v -map 1:a \
    -c:v libx264 -preset ultrafast -pix_fmt yuv420p \
    -c:a ac3 -b:a 128k \
    -metadata:s:a:0 language=eng \
    "$TARGET/sub.mkv"

# Dieselbe Datei mit einer externen Untertiteldatei daneben. mpv lädt sie beim
# Öffnen automatisch, und der Test prüft, dass sie als `external` erscheint.
echo "→ $TARGET/sub.srt"
cat > "$TARGET/sub.srt" <<'SRT'
1
00:00:00,500 --> 00:00:03,000
Erste Untertitelzeile

2
00:00:03,500 --> 00:00:06,000
Zweite Untertitelzeile
SRT

echo "Fertig:"
ls -la "$TARGET"
