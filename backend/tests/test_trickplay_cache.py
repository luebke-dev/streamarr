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


def test_purge_orphans_keeps_known_files_and_drops_the_rest(tmp_path):
    """A file moved or renamed outside the app leaves an entry nobody claims."""
    with _cache_root(tmp_path):
        known = "/library/movies/keep.mkv"
        moved_away = "/library/movies/old-name.mkv"
        for path in (known, moved_away):
            directory = trickplay.cache_dir(path)
            directory.mkdir(parents=True)
            (directory / "sprite_000.webp").write_bytes(b"x" * 10)

        result = trickplay.purge_orphans([known])

        assert result["scanned"] == 2
        assert result["deleted"] == 1
        assert result["bytes_freed"] == 10
        assert trickplay.cache_dir(known).exists()
        assert not trickplay.cache_dir(moved_away).exists()


def test_purge_orphans_on_empty_cache_is_a_no_op(tmp_path):
    with _cache_root(tmp_path):
        assert trickplay.purge_orphans(["/library/movies/heat.mkv"]) == {
            "scanned": 0,
            "deleted": 0,
            "bytes_freed": 0,
            "failed": 0,
        }
