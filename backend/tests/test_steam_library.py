"""Tests for the local Steam library reader (streamarr.services.steam_library)."""

from pathlib import Path

from streamarr.services.steam_library import (
    _iter_library_paths,
    _parse_appmanifest,
    _parse_vdf,
    _tokenize,
    read_steam_library,
)

# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _appmanifest(app_id: str, name: str, *, installdir: str | None = None) -> str:
    installdir = installdir or name.replace(" ", "")
    return (
        '"AppState"\n'
        "{\n"
        f'\t"appid"\t\t"{app_id}"\n'
        '\t"universe"\t\t"1"\n'
        f'\t"name"\t\t"{name}"\n'
        '\t"StateFlags"\t\t"4"\n'
        f'\t"installdir"\t\t"{installdir}"\n'
        '\t"LastUpdated"\t\t"1700000000"\n'
        "}\n"
    )


def _write_manifest(steamapps: Path, app_id: str, name: str) -> None:
    steamapps.mkdir(parents=True, exist_ok=True)
    (steamapps / f"appmanifest_{app_id}.acf").write_text(
        _appmanifest(app_id, name), encoding="utf-8"
    )


def _localconfig(app_ids: list[str]) -> str:
    apps_block = "".join(
        f'\t\t\t\t\t"{aid}"\n\t\t\t\t\t{{\n\t\t\t\t\t\t"LastPlayed"\t\t"1699999999"\n\t\t\t\t\t}}\n'
        for aid in app_ids
    )
    return (
        '"UserLocalConfigStore"\n'
        "{\n"
        '\t"Software"\n'
        "\t{\n"
        '\t\t"Valve"\n'
        "\t\t{\n"
        '\t\t\t"Steam"\n'
        "\t\t\t{\n"
        '\t\t\t\t"apps"\n'
        "\t\t\t\t{\n"
        f"{apps_block}"
        "\t\t\t\t}\n"
        "\t\t\t}\n"
        "\t\t}\n"
        "\t}\n"
        "}\n"
    )


def _write_localconfig(steam_dir: Path, account_id: str, app_ids: list[str]) -> None:
    config = steam_dir / "userdata" / account_id / "config"
    config.mkdir(parents=True, exist_ok=True)
    (config / "localconfig.vdf").write_text(_localconfig(app_ids), encoding="utf-8")


def _libraryfolders_nested(paths: list[str]) -> str:
    blocks = "".join(
        f'\t"{i}"\n\t{{\n\t\t"path"\t\t"{p}"\n\t\t"label"\t\t""\n\t}}\n'
        for i, p in enumerate(paths)
    )
    return '"libraryfolders"\n{\n' + blocks + "}\n"


# ---------------------------------------------------------------------------
# Tokenizer / parser unit tests
# ---------------------------------------------------------------------------


class TestTokenizer:
    def test_basic_pairs_and_braces(self):
        kinds = [k for k, _ in _tokenize('"a" { "b" "c" }')]
        assert kinds == ["str", "lbrace", "str", "str", "rbrace"]

    def test_escaped_characters(self):
        toks = list(_tokenize(r'"path" "C:\\Games\\Steam"'))
        assert toks[1] == ("str", "C:\\Games\\Steam")

    def test_quote_escape_inside_value(self):
        toks = list(_tokenize(r'"k" "say \"hi\""'))
        assert toks[1] == ("str", 'say "hi"')

    def test_line_comments_skipped(self):
        toks = list(_tokenize('// a comment\n"k" "v" // trailing\n'))
        assert toks == [("str", "k"), ("str", "v")]

    def test_unquoted_tokens(self):
        toks = list(_tokenize("key value { nested 1 }"))
        assert toks == [
            ("str", "key"),
            ("str", "value"),
            ("lbrace", "{"),
            ("str", "nested"),
            ("str", "1"),
            ("rbrace", "}"),
        ]


class TestParser:
    def test_nested_dict(self):
        parsed = _parse_vdf('"root" { "a" "1" "b" { "c" "2" } }')
        assert parsed == {"root": {"a": "1", "b": {"c": "2"}}}

    def test_multiple_top_level_keys(self):
        parsed = _parse_vdf('"x" "1"\n"y" "2"\n')
        assert parsed == {"x": "1", "y": "2"}

    def test_tolerates_trailing_key_without_value(self):
        # Should not raise; the dangling key is simply dropped.
        parsed = _parse_vdf('"a" "1"\n"dangling"')
        assert parsed == {"a": "1"}

    def test_tolerates_unbalanced_close_brace(self):
        parsed = _parse_vdf('"a" "1" } "b" "2"')
        assert parsed.get("a") == "1"
        assert parsed.get("b") == "2"

    def test_empty_string_returns_empty_dict(self):
        assert _parse_vdf("") == {}


class TestAppManifestParsing:
    def test_extracts_id_and_name(self, tmp_path):
        acf = tmp_path / "appmanifest_220.acf"
        acf.write_text(_appmanifest("220", "Half-Life 2"), encoding="utf-8")
        assert _parse_appmanifest(acf) == {
            "app_id": "220",
            "name": "Half-Life 2",
            "installed": True,
        }

    def test_missing_name_yields_none(self, tmp_path):
        acf = tmp_path / "appmanifest_10.acf"
        acf.write_text('"AppState" { "appid" "10" }', encoding="utf-8")
        entry = _parse_appmanifest(acf)
        assert entry == {"app_id": "10", "name": None, "installed": True}

    def test_non_numeric_appid_rejected(self, tmp_path):
        acf = tmp_path / "appmanifest_bad.acf"
        acf.write_text('"AppState" { "appid" "abc" "name" "X" }', encoding="utf-8")
        assert _parse_appmanifest(acf) is None

    def test_missing_appstate_returns_none(self, tmp_path):
        acf = tmp_path / "appmanifest_x.acf"
        acf.write_text('"Something" { "appid" "5" }', encoding="utf-8")
        assert _parse_appmanifest(acf) is None


class TestLibraryFolders:
    def test_nested_format(self):
        vdf = _parse_vdf(_libraryfolders_nested(["/a/lib", "/b/lib"]))
        assert list(_iter_library_paths(vdf)) == ["/a/lib", "/b/lib"]

    def test_legacy_flat_format_skips_metadata(self):
        text = (
            '"LibraryFolders"\n{\n'
            '\t"TimeNextStatsReport"\t\t"123"\n'
            '\t"ContentStatsID"\t\t"456"\n'
            '\t"1"\t\t"/mnt/games/SteamLibrary"\n'
            "}\n"
        )
        vdf = _parse_vdf(text)
        assert list(_iter_library_paths(vdf)) == ["/mnt/games/SteamLibrary"]

    def test_missing_root_yields_nothing(self):
        assert list(_iter_library_paths({"other": {}})) == []


# ---------------------------------------------------------------------------
# read_steam_library end-to-end
# ---------------------------------------------------------------------------


class TestReadSteamLibrary:
    def test_empty_or_missing_dir_returns_empty(self, tmp_path):
        assert read_steam_library(tmp_path) == []
        assert read_steam_library(tmp_path / "does-not-exist") == []

    def test_accepts_pathlike_and_str(self, tmp_path):
        steamapps = tmp_path / ".local/share/Steam/steamapps"
        _write_manifest(steamapps, "220", "Half-Life 2")
        from_path = read_steam_library(tmp_path)
        from_str = read_steam_library(str(tmp_path))
        assert from_path == from_str
        assert from_path == [
            {"app_id": "220", "name": "Half-Life 2", "installed": True}
        ]

    def test_installed_only_local_share_layout(self, tmp_path):
        steamapps = tmp_path / ".local/share/Steam/steamapps"
        _write_manifest(steamapps, "220", "Half-Life 2")
        _write_manifest(steamapps, "440", "Team Fortress 2")
        result = read_steam_library(tmp_path)
        assert result == [
            {"app_id": "220", "name": "Half-Life 2", "installed": True},
            {"app_id": "440", "name": "Team Fortress 2", "installed": True},
        ]

    def test_dot_steam_layout(self, tmp_path):
        steamapps = tmp_path / ".steam/steam/steamapps"
        _write_manifest(steamapps, "620", "Portal 2")
        result = read_steam_library(tmp_path)
        assert result == [
            {"app_id": "620", "name": "Portal 2", "installed": True}
        ]

    def test_owned_only_from_localconfig(self, tmp_path):
        steam_dir = tmp_path / ".local/share/Steam"
        # A steamapps dir must exist for the Steam dir to be recognised.
        (steam_dir / "steamapps").mkdir(parents=True)
        _write_localconfig(steam_dir, "123456", ["570", "730"])
        result = read_steam_library(tmp_path)
        assert result == [
            {"app_id": "570", "name": None, "installed": False},
            {"app_id": "730", "name": None, "installed": False},
        ]

    def test_installed_takes_precedence_over_owned(self, tmp_path):
        steam_dir = tmp_path / ".local/share/Steam"
        steamapps = steam_dir / "steamapps"
        _write_manifest(steamapps, "730", "Counter-Strike 2")
        # 730 owned+installed, 570 owned-only.
        _write_localconfig(steam_dir, "123456", ["730", "570"])
        result = read_steam_library(tmp_path)
        # Named (installed) entry sorts before the unnamed owned-only one.
        assert result == [
            {"app_id": "730", "name": "Counter-Strike 2", "installed": True},
            {"app_id": "570", "name": None, "installed": False},
        ]

    def test_extra_library_folder_scanned(self, tmp_path):
        steam_dir = tmp_path / ".local/share/Steam"
        primary = steam_dir / "steamapps"
        _write_manifest(primary, "220", "Half-Life 2")

        # A second library on another "disk".
        extra_lib = tmp_path / "mnt" / "games" / "SteamLibrary"
        extra_steamapps = extra_lib / "steamapps"
        _write_manifest(extra_steamapps, "1091500", "Cyberpunk 2077")

        (primary / "libraryfolders.vdf").write_text(
            _libraryfolders_nested([str(steam_dir), str(extra_lib)]),
            encoding="utf-8",
        )

        result = read_steam_library(tmp_path)
        assert result == [
            {"app_id": "1091500", "name": "Cyberpunk 2077", "installed": True},
            {"app_id": "220", "name": "Half-Life 2", "installed": True},
        ]

    def test_dedup_across_layouts_and_libraries(self, tmp_path):
        # Same game present in both .local/share and .steam layouts.
        a = tmp_path / ".local/share/Steam/steamapps"
        b = tmp_path / ".steam/steam/steamapps"
        _write_manifest(a, "440", "Team Fortress 2")
        _write_manifest(b, "440", "Team Fortress 2")
        result = read_steam_library(tmp_path)
        assert result == [
            {"app_id": "440", "name": "Team Fortress 2", "installed": True}
        ]

    def test_denylist_filters_redistributables(self, tmp_path):
        steamapps = tmp_path / ".local/share/Steam/steamapps"
        _write_manifest(steamapps, "220", "Half-Life 2")
        _write_manifest(steamapps, "228980", "Steamworks Common Redistributables")
        _write_manifest(steamapps, "1628350", "Steam Linux Runtime 3.0 (sniper)")
        _write_manifest(steamapps, "2348590", "Proton 9.0 (Beta)")
        result = read_steam_library(tmp_path)
        assert result == [
            {"app_id": "220", "name": "Half-Life 2", "installed": True}
        ]

    def test_denylist_filters_owned_redistributable_without_name(self, tmp_path):
        steam_dir = tmp_path / ".local/share/Steam"
        (steam_dir / "steamapps").mkdir(parents=True)
        _write_localconfig(steam_dir, "1", ["570", "228980"])
        result = read_steam_library(tmp_path)
        assert result == [
            {"app_id": "570", "name": None, "installed": False}
        ]

    def test_game_named_proton_is_not_filtered(self, tmp_path):
        # A bare "Proton" name must survive the name heuristic.
        steamapps = tmp_path / ".local/share/Steam/steamapps"
        _write_manifest(steamapps, "999999", "Proton")
        result = read_steam_library(tmp_path)
        assert result == [
            {"app_id": "999999", "name": "Proton", "installed": True}
        ]

    def test_sorted_by_name_then_owned_last(self, tmp_path):
        steam_dir = tmp_path / ".local/share/Steam"
        steamapps = steam_dir / "steamapps"
        _write_manifest(steamapps, "440", "Team Fortress 2")
        _write_manifest(steamapps, "220", "Half-Life 2")
        _write_manifest(steamapps, "620", "portal 2")  # lowercase to test CI sort
        _write_localconfig(steam_dir, "1", ["570", "730"])
        result = read_steam_library(tmp_path)
        names = [g["name"] for g in result]
        # Named entries alphabetical (case-insensitive), owned-only (None) last.
        assert names == ["Half-Life 2", "portal 2", "Team Fortress 2", None, None]
        # Owned-only tail ordered by numeric app id.
        assert [g["app_id"] for g in result[-2:]] == ["570", "730"]

    def test_malformed_manifest_is_skipped(self, tmp_path):
        steamapps = tmp_path / ".local/share/Steam/steamapps"
        steamapps.mkdir(parents=True)
        _write_manifest(steamapps, "220", "Half-Life 2")
        (steamapps / "appmanifest_broken.acf").write_text(
            '"AppState" { "appid" ', encoding="utf-8"
        )
        result = read_steam_library(tmp_path)
        assert result == [
            {"app_id": "220", "name": "Half-Life 2", "installed": True}
        ]
