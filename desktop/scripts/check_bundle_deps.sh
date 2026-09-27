#!/usr/bin/env bash
# Prüft, dass die gebauten Linux-Pakete jede direkt gelinkte Bibliothek
# deklarieren.
#
# Warum das ein Skript ist und keine einmalige Sichtprüfung: die Abhängigkeiten
# sind nicht statisch. `libudev` kam erst mit dem `gamepad`-Feature dazu, und
# Tauri deklariert von sich aus nur `libwebkit2gtk-4.1-0` und `libgtk-3-0`. Ein
# Paket, dem eine Bibliothek fehlt, installiert sauber und stürzt beim Start ab —
# der Fehler zeigt sich also erst beim Nutzer.
#
# Aufruf: desktop/scripts/check_bundle_deps.sh <pfad-zu-Streamarr> <deb> <rpm>
set -euo pipefail

BINARY="${1:?Pfad zum Binary fehlt}"
DEB="${2:?Pfad zum .deb fehlt}"
RPM="${3:?Pfad zum .rpm fehlt}"

fail=0

# Soname -> Debian-Paket, Fedora-Paket. Nur die Bibliotheken, die die App
# wirklich selbst linkt (DT_NEEDED), nicht die transitiv geladenen - für die
# bürgt das jeweils liefernde Paket.
#
# Ein leeres Ergebnis heißt "gehört zur glibc, kein eigenes Paket". Das wird
# nicht als Leerstring zurückgegeben, sondern als das Wort `builtin`: ein
# Leerstring ist von "unbekannte Soname" nicht zu unterscheiden, und der erste
# Lauf dieses Skripts hat genau daran die vier glibc-Bibliotheken als Lücke
# gemeldet.
map_soname() {
  case "$1" in
    libwebkit2gtk-4.1.so.0) echo "libwebkit2gtk-4.1-0 webkit2gtk4.1" ;;
    libgtk-3.so.0|libgdk-3.so.0) echo "libgtk-3-0 gtk3" ;;
    libjavascriptcoregtk-4.1.so.0) echo "libjavascriptcoregtk-4.1-0 javascriptcoregtk4.1" ;;
    libsoup-3.0.so.0) echo "libsoup-3.0-0 libsoup3" ;;
    libglib-2.0.so.0|libgio-2.0.so.0|libgobject-2.0.so.0) echo "libglib2.0-0 glib2" ;;
    libcairo.so.2) echo "libcairo2 cairo" ;;
    libgdk_pixbuf-2.0.so.0) echo "libgdk-pixbuf-2.0-0 gdk-pixbuf2" ;;
    libudev.so.1) echo "libudev1 systemd-libs" ;;
    libssl.so.3|libcrypto.so.3) echo "libssl3 openssl-libs" ;;
    # libc, libm und der dynamische Lader sind Teil jeder glibc-Installation und
    # werden von keinem Paket einzeln deklariert.
    libc.so.6|libm.so.6|libgcc_s.so.1|ld-linux-x86-64.so.2) echo "builtin builtin" ;;
    *) echo "" ;;
  esac
}

DEB_DEPS="$(dpkg-deb -f "$DEB" Depends | tr ',' '\n' | sed 's/^ *//;s/ *$//')"
RPM_DEPS="$(rpm -qpR "$RPM" 2>/dev/null | tr ',' '\n' | sed 's/^ *//;s/ *$//')"

echo "== Deklarierte Abhängigkeiten =="
echo "  DEB: $(echo "$DEB_DEPS" | tr '\n' ' ')"
echo "  RPM: $(echo "$RPM_DEPS" | grep -v '()(64bit)' | tr '\n' ' ')"
echo

echo "== Direkt gelinkte Bibliotheken =="
while read -r so; do
  [ -n "$so" ] || continue
  names="$(map_soname "$so")"
  if [ "$names" = "builtin builtin" ]; then
    continue
  fi
  if [ -z "$names" ]; then
    # Unbekannt: das ist selbst ein Befund, denn dann prüft dieses Skript die
    # Bibliothek nicht und eine künftige Änderung bliebe unbemerkt.
    echo "  $so -> UNBEKANNT (bitte in map_soname aufnehmen)"
    fail=1
    continue
  fi
  deb_pkg="${names%% *}"
  rpm_pkg="${names##* }"

  if ! echo "$DEB_DEPS" | grep -qx "$deb_pkg"; then
    echo "  FEHLT im DEB: $deb_pkg (für $so)"
    fail=1
  fi
  if ! echo "$RPM_DEPS" | grep -qE "^${rpm_pkg}(\(\(64bit\)\))?$"; then
    echo "  FEHLT in RPM: $rpm_pkg (für $so)"
    fail=1
  fi
done < <(objdump -p "$BINARY" | awk '/NEEDED/ {print $2}' | sort -u)

echo
echo "== Doppelte Einträge =="
dupes="$(echo "$DEB_DEPS" | sort | uniq -d)"
if [ -n "$dupes" ]; then
  # Tauri hängt seine eigenen zwei Einträge an eine eigene Liste an, sodass ein
  # Wiederholen dort zu Dubletten führt. Harmlos, aber unsauber.
  echo "  DOPPELT im DEB: $dupes"
  fail=1
else
  echo "  keine"
fi

if [ "$fail" -ne 0 ]; then
  echo
  echo "FEHLGESCHLAGEN: die Pakete sind unvollständig."
  exit 1
fi
echo
echo "OK: jedes DT_NEEDED ist deklariert."
