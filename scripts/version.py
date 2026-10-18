#!/usr/bin/env python3
"""One product version, six places, one command.

Streamarr is not one artifact: the backend is a Python package, the web UI and
the two shells are npm packages, the Tauri shell is also a Rust crate, and the
desktop app decides whether to offer an update by comparing its *own* version
against the release feed. A version that disagrees with itself is therefore not
cosmetic - it makes a user either miss an update or be offered one they already
have.

`VERSION` is the only file a human edits. `set` writes it to every manifest, and
`check` fails when any of them drifts. Both run in CI, so a release tag that does
not match the manifests never reaches a registry.

Usage:
    scripts/version.py show          # print the product version
    scripts/version.py check         # exit 1 if any manifest disagrees
    scripts/version.py set 2026.3.0  # write the version everywhere
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "VERSION"

# Scheme: year.release.patch - 2026.2.1 is the second release line of 2026, first
# patch. Nothing else in the repo may invent a second scheme for a shipped piece.
SEMVERISH = re.compile(r"^(?P<year>\d{4})\.(?P<release>\d+)\.(?P<patch>\d+)$")

JSON_TARGETS = [
    ROOT / "frontend" / "package.json",
    ROOT / "frontend" / "src-capacitor" / "package.json",
    ROOT / "frontend" / "src-tauri" / "tauri.conf.json",
]
TOML_TARGETS = [
    ROOT / "backend" / "pyproject.toml",
    ROOT / "frontend" / "src-tauri" / "Cargo.toml",
]

# Crates and services that are internal: they are not shipped to anyone, so they
# carry their own version and are deliberately not touched here.
INTERNAL = [
    ROOT / "frontend" / "src-tauri" / "player" / "Cargo.toml",
    ROOT / "lightrays" / "Cargo.toml",
    ROOT / "downloaders" / "torrent" / "Cargo.toml",
    ROOT / "downloaders" / "usenet" / "Cargo.toml",
    ROOT / "downloaders" / "spotify" / "Cargo.toml",
]


def read_version() -> str:
    if not VERSION_FILE.exists():
        sys.exit("VERSION is missing - it is the source of truth")
    return VERSION_FILE.read_text(encoding="utf-8").strip()


def _read_json_version(path: Path) -> str | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8")).get("version")


def _package_section(text: str) -> str | None:
    match = re.search(r"^\[package\]\s*$(.*?)(?=^\[|\Z)", text, re.M | re.S)
    return match.group(1) if match else None


def _read_toml_version(path: Path) -> str | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    section = re.search(r"^\[project\]\s*$(.*?)(?=^\[|\Z)", text, re.M | re.S)
    if section:
        match = re.search(r'^version\s*=\s*"([^"]+)"', section.group(1), re.M)
        if match:
            return match.group(1)
    package = _package_section(text)
    if package:
        match = re.search(r'^version\s*=\s*"([^"]+)"', package, re.M)
        if match:
            return match.group(1)
    return None


def _write_json_version(path: Path, version: str) -> None:
    """Rewrite the version in place.

    Re-serialising the JSON would reflow every inline array and decode every
    escape sequence in the file, turning a one-word version bump into a diff
    nobody wants to review. The files have exactly one ``"version"`` key, so a
    targeted substitution is both safe and byte-preserving everywhere else.
    """
    text = path.read_text(encoding="utf-8")
    new_text, count = re.subn(
        r'("version"\s*:\s*")([^"]+)(")',
        lambda m: f"{m.group(1)}{version}{m.group(3)}",
        text,
        count=1,
    )
    if count != 1:
        sys.exit(f"no version key found in {path.relative_to(ROOT)}")
    path.write_text(new_text, encoding="utf-8")


def _write_toml_version(path: Path, version: str) -> None:
    text = path.read_text(encoding="utf-8")
    new_text, count = re.subn(
        r'(^version\s*=\s*")([^"]+)(")',
        lambda m: f"{m.group(1)}{version}{m.group(3)}",
        text,
        count=1,
        flags=re.M,
    )
    if count != 1:
        sys.exit(f"no version line found in {path.relative_to(ROOT)}")
    path.write_text(new_text, encoding="utf-8")


def _all_versions() -> dict[str, str | None]:
    found: dict[str, str | None] = {"VERSION": read_version()}
    for path in JSON_TARGETS:
        found[str(path.relative_to(ROOT))] = _read_json_version(path)
    for path in TOML_TARGETS:
        found[str(path.relative_to(ROOT))] = _read_toml_version(path)
    return found


def cmd_show() -> int:
    print(read_version())
    return 0


def cmd_check() -> int:
    version = read_version()
    if not SEMVERISH.match(version):
        sys.exit(f"VERSION '{version}' is not year.release.patch")

    failures: list[str] = []
    for name, found in _all_versions().items():
        if found is None:
            failures.append(f"{name}: no version found")
        elif found != version:
            failures.append(f"{name}: {found} != {version}")

    # A tag is the other place the version is stated, so it has to agree too.
    tag = (sys.argv[2] if len(sys.argv) > 2 else "").strip()
    if not tag:
        import os

        tag = os.environ.get("GITHUB_REF_NAME", "").strip()
    if tag.startswith("v") and tag[1:] != version:
        failures.append(f"tag {tag} != VERSION {version}")

    if failures:
        print(f"version mismatch (VERSION says {version}):", *failures, sep="\n  ")
        return 1

    print(f"OK: every manifest says {version}")
    return 0


def cmd_set(new_version: str) -> int:
    if not SEMVERISH.match(new_version):
        sys.exit(f"'{new_version}' is not year.release.patch (e.g. 2026.3.0)")

    previous = read_version()
    VERSION_FILE.write_text(f"{new_version}\n", encoding="utf-8")
    for path in JSON_TARGETS:
        _write_json_version(path, new_version)
    for path in TOML_TARGETS:
        _write_toml_version(path, new_version)

    internal = []
    for path in INTERNAL:
        if path.exists():
            internal.append(f"{path.relative_to(ROOT)} @ {_read_toml_version(path)}")
    print(f"{previous} -> {new_version}")
    for name, found in _all_versions().items():
        print(f"  {name}: {found}")
    if internal:
        print("left alone (internal, not shipped):")
        for line in internal:
            print(f"  {line}")
    print("next: update CHANGELOG.md, commit, then tag v" + new_version)
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] in {"-h", "--help", "help"}:
        print(__doc__)
        return 0 if len(argv) > 1 else 2
    command = argv[1]
    if command == "show":
        return cmd_show()
    if command == "check":
        return cmd_check()
    if command == "set":
        if len(argv) < 3:
            sys.exit("usage: scripts/version.py set 2026.3.0")
        return cmd_set(argv[2])
    sys.exit(f"unknown command: {command}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
