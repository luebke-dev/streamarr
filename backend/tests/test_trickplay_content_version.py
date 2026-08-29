import os

from streamarr.services import trickplay


def test_trickplay_cache_key_changes_with_content_version(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    media = tmp_path / "movie.mkv"
    media.write_bytes(b"first")
    monkeypatch.setattr(trickplay, "_root", lambda: cache)

    first = trickplay.cache_dir(str(media))
    stat = media.stat()
    media.write_bytes(b"second-version")
    os.utime(media, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    second = trickplay.cache_dir(str(media))

    assert first.parent == cache
    assert first != second


def test_chapters_are_normalized_from_probe_data():
    chapters = trickplay.chapters_from_probe(
        {
            "chapters": [
                {
                    "start_time": "1.25",
                    "end_time": "15.5",
                    "tags": {"title": "Opening"},
                },
                {"start_time": "15.5", "end_time": "30"},
            ]
        }
    )

    assert chapters == [
        {"title": "Opening", "start_seconds": 1.25, "end_seconds": 15.5},
        {"title": "Chapter 2", "start_seconds": 15.5, "end_seconds": 30.0},
    ]
