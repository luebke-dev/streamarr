"""Trickplay sprite cache: keyed by source file, dropped with the source file."""

from unittest.mock import patch

from streamarr.services import trickplay


def _cache_root(tmp_path):
    """Point the cache at a temp dir instead of /cache."""
    return patch.object(trickplay, "_root", lambda: tmp_path)


def test_key_is_stable_per_file_and_differs_between_files():
    key = trickplay.cache_key("/library/movies/heat.mkv")

    assert key == trickplay.cache_key("/library/movies/heat.mkv")
    assert key != trickplay.cache_key("/library/movies/other.mkv")


def test_two_sessions_of_the_same_file_share_one_cache_dir(tmp_path):
    """The point of the cache: replaying a file must not regenerate sprites."""
    with _cache_root(tmp_path):
        first = trickplay.cache_dir("/library/movies/heat.mkv")
        second = trickplay.cache_dir("/library/movies/heat.mkv")

    assert first == second


def test_incomplete_run_is_not_reused(tmp_path):
    """Sheets without the marker are a partial run — reusing them would leave
    the tail of the seek bar blank forever."""
    with _cache_root(tmp_path):
        directory = trickplay.cache_dir("/library/movies/heat.mkv")
        directory.mkdir(parents=True)
        (directory / "sprite_000.webp").write_bytes(b"partial")

        assert trickplay.sprites("/library/movies/heat.mkv")
        assert not trickplay.is_complete("/library/movies/heat.mkv")

        (directory / trickplay.COMPLETE_MARKER).touch()
        assert trickplay.is_complete("/library/movies/heat.mkv")


def test_marker_without_sheets_is_not_complete(tmp_path):
    with _cache_root(tmp_path):
        directory = trickplay.cache_dir("/library/movies/heat.mkv")
        directory.mkdir(parents=True)
        (directory / trickplay.COMPLETE_MARKER).touch()

        assert not trickplay.is_complete("/library/movies/heat.mkv")


def test_purge_drops_the_cache_for_that_file_only(tmp_path):
    with _cache_root(tmp_path):
        kept = trickplay.cache_dir("/library/movies/keep.mkv")
        dropped = trickplay.cache_dir("/library/movies/drop.mkv")
        for directory in (kept, dropped):
            directory.mkdir(parents=True)
            (directory / "sprite_000.webp").write_bytes(b"x")
            (directory / trickplay.COMPLETE_MARKER).touch()

        assert trickplay.purge("/library/movies/drop.mkv") is True

        assert not dropped.exists()
        assert trickplay.is_complete("/library/movies/keep.mkv")


def test_purge_of_uncached_file_is_a_no_op(tmp_path):
    with _cache_root(tmp_path):
        assert trickplay.purge("/library/movies/never-played.mkv") is False
