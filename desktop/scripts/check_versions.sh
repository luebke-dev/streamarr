#!/usr/bin/env bash
# Prüft, dass alle Versionsangaben der Desktop-App übereinstimmen.
#
# Warum das ein Skript ist: die Version steht an vier Stellen, und drei davon
# werden von Werkzeugen gelesen, die einander nicht kennen.
#
#   frontend/package.json            die Web-UI, und was `yarn` anzeigt
#   frontend/src-tauri/Cargo.toml    die Shell, und damit das Binary
#   frontend/src-tauri/tauri.conf.json  was der Bundler ins Paket schreibt
#   desktop/player/Cargo.toml        der Player-Kern
#
# Eine Abweichung ist nicht kosmetisch. Der Update-Prüfer vergleicht die Version
# des *laufenden* Builds (`tauri.conf.json`) mit der des Feeds; steht dort eine
# andere als in `Cargo.toml`, kann ein Nutzer ein Update angeboten bekommen, das
# er bereits hat, oder — schlimmer — gar keines, obwohl eines vorliegt. Und das
# `.deb` trägt die Version aus `tauri.conf.json`, während `dpkg` sie gegen die
# des bereits installierten Pakets hält: ein Auseinanderlaufen erzeugt dort ein
# Paket, das sich nicht sauber aktualisieren lässt.
#
# Aufruf: desktop/scripts/check_versions.sh
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$root"

read_json_version() {
  python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['version'])" "$1"
}

read_cargo_version() {
  python3 - "$1" <<'PY'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
# Nur die `[package]`-Sektion: ein `version = ` in einer Abhängigkeit ist eine
# Anforderung, keine Version dieser Kiste.
section = re.search(r"^\[package\]\s*$(.*?)(?=^\[|\Z)", text, re.M | re.S)
if not section:
    sys.exit(f"keine [package]-Sektion in {sys.argv[1]}")
match = re.search(r'^version\s*=\s*"([^"]+)"', section.group(1), re.M)
if not match:
    sys.exit(f"keine version in [package] von {sys.argv[1]}")
print(match.group(1))
PY
}

package_json="$(read_json_version frontend/package.json)"
shell_cargo="$(read_cargo_version frontend/src-tauri/Cargo.toml)"
tauri_conf="$(read_json_version frontend/src-tauri/tauri.conf.json)"
player_cargo="$(read_cargo_version desktop/player/Cargo.toml)"

echo "== Versionen =="
printf '  %-34s %s\n' "frontend/package.json" "$package_json"
printf '  %-34s %s\n' "frontend/src-tauri/Cargo.toml" "$shell_cargo"
printf '  %-34s %s\n' "frontend/src-tauri/tauri.conf.json" "$tauri_conf"
printf '  %-34s %s\n' "desktop/player/Cargo.toml" "$player_cargo"
echo

fail=0

# Die drei, die das *Produkt* beschreiben, müssen gleich sein. `desktop/player`
# ist eine Bibliothek und wird nicht ausgeliefert; ihre Version folgt der
# Cargo-Konvention und muss nicht mitwandern. Dass sie es *nicht* tut, wird
# ausdrücklich berichtet statt stillschweigend geduldet — sonst liest sich eine
# Ausgabe mit vier verschiedenen Zahlen wie ein Fehler.
for name in "frontend/src-tauri/Cargo.toml:$shell_cargo" \
            "frontend/src-tauri/tauri.conf.json:$tauri_conf"; do
  file="${name%%:*}"
  value="${name#*:}"
  if [ "$value" != "$package_json" ]; then
    echo "FEHLER: $file steht auf $value, frontend/package.json auf $package_json"
    fail=1
  fi
done

if [ "$fail" -eq 0 ]; then
  echo "OK: Produktversion ist überall $package_json."
else
  echo
  echo "Die Produktversion muss an allen drei Stellen gleich sein."
  echo "Diese Dateien werden von verschiedenen Werkzeugen gelesen: der Bundler"
  echo "nimmt tauri.conf.json, das Binary Cargo.toml, die UI package.json."
  exit 1
fi

# Ein Hinweis, kein Fehler: `desktop/player` ist eine interne Bibliothek.
if [ "$player_cargo" = "$package_json" ]; then
  echo "Hinweis: desktop/player trägt dieselbe Version wie das Produkt."
else
  echo "Hinweis: desktop/player ist eine interne Bibliothek (Version $player_cargo)"
  echo "         und wird nicht ausgeliefert — das ist in Ordnung."
fi
