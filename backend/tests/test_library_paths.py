from types import SimpleNamespace

from streamarr.services.library_paths import (
    library_processing_options,
    library_root_paths,
    parse_library_settings,
)


def test_library_roots_are_canonical_and_deduplicated(tmp_path):
    primary = tmp_path / "movies"
    secondary = tmp_path / "archive"
    library = SimpleNamespace(
        path=str(primary),
        settings={
            "media_folders": [str(primary / "."), str(secondary), str(secondary)]
        },
    )

    assert library_root_paths(library) == [str(primary), str(secondary)]


def test_library_options_support_json_settings():
    library = SimpleNamespace(
        path="/library/movies",
        settings='{"options":{"trickplay_enabled":false}}',
    )

    assert parse_library_settings(library.settings)["options"]
    assert library_processing_options(library) == {"trickplay_enabled": False}
