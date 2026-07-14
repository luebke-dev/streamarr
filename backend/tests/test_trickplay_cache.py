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


def _entry(path, *, size, age_seconds, complete=True):
    """Create a cache entry of a given size, last used `age_seconds` ago."""
    import os

    directory = trickplay.cache_dir(path)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "sprite_000.webp").write_bytes(b"x" * size)
    if complete:
        (directory / trickplay.COMPLETE_MARKER).touch()
    used_at = 1_000_000.0 - age_seconds
    os.utime(directory, (used_at, used_at))
    return directory


def test_under_budget_evicts_nothing(tmp_path):
    with _cache_root(tmp_path):
        _entry("/library/a.mkv", size=100, age_seconds=99999)

        result = trickplay.enforce_size_limit(1000, now=1_000_000.0)

        assert result["deleted"] == 0
        assert trickplay.cache_dir("/library/a.mkv").exists()


def test_evicts_least_recently_used_first(tmp_path):
    with _cache_root(tmp_path):
        _entry("/library/old.mkv", size=100, age_seconds=90000)
        _entry("/library/recent.mkv", size=100, age_seconds=7200)

        result = trickplay.enforce_size_limit(150, now=1_000_000.0)

        assert result["deleted"] == 1
        assert not trickplay.cache_dir("/library/old.mkv").exists()
        assert trickplay.cache_dir("/library/recent.mkv").exists()


def test_never_evicts_an_entry_that_is_in_use(tmp_path):
    """A film being watched must keep its thumbnails, budget or not."""
    with _cache_root(tmp_path):
        _entry("/library/playing-now.mkv", size=5000, age_seconds=5)

        result = trickplay.enforce_size_limit(100, now=1_000_000.0)

        assert result["deleted"] == 0
        assert trickplay.cache_dir("/library/playing-now.mkv").exists()


def test_never_evicts_a_run_still_generating(tmp_path):
    """No .complete marker means FFmpeg is still writing sheets."""
    with _cache_root(tmp_path):
        _entry("/library/generating.mkv", size=5000, age_seconds=90000, complete=False)

        result = trickplay.enforce_size_limit(100, now=1_000_000.0)

        assert result["deleted"] == 0
        assert trickplay.cache_dir("/library/generating.mkv").exists()


def test_a_long_film_always_fits_the_default_budget():
    """The budget must never be so tight that one film cannot be cached.

    A 4-hour film needs ~1440 thumbnails = 15 sheets; even at a generous
    600 KB per sheet that is ~9 MB, far below the default budget.
    """
    sheets_for_four_hours = (4 * 3600 // 10 + 99) // 100
    worst_case_bytes = sheets_for_four_hours * 600 * 1024

    assert worst_case_bytes < trickplay.bytes_for_gb(None) / 100


def test_budget_comes_from_the_configured_value():
    assert trickplay.bytes_for_gb(2) == 2 * 1024**3
    assert trickplay.bytes_for_gb(0.5) == int(0.5 * 1024**3)
    # Unset falls back to the default, 0 disables the limit entirely.
    assert trickplay.bytes_for_gb(None) == int(trickplay.DEFAULT_MAX_CACHE_GB * 1024**3)
    assert trickplay.bytes_for_gb(0) == 0


def test_unlimited_budget_evicts_nothing(tmp_path):
    with _cache_root(tmp_path):
        _entry("/library/a.mkv", size=5000, age_seconds=99999)

        result = trickplay.enforce_size_limit(0, now=1_000_000.0)

        assert result["deleted"] == 0
        assert trickplay.cache_dir("/library/a.mkv").exists()
