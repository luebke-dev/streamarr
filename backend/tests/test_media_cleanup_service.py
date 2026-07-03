"""Tests for MediaService.

File-system operations are exercised via pytest's tmp_path fixture; glob calls
that reference hardcoded /temp/ paths are patched to use the temporary directory.
"""

import time
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.services.media import MediaService, cleanup_stream_on_stop


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_service(db_session: AsyncSession) -> MediaService:
    return MediaService(db_session)


# ---------------------------------------------------------------------------
# cleanup_temp_files
# ---------------------------------------------------------------------------


class TestCleanupTempFiles:
    """Tests for MediaService.cleanup_temp_files()."""

    @pytest.mark.asyncio
    async def test_cleanup_deletes_matching_m3u8(
        self, db_session: AsyncSession, tmp_path: Path
    ):
        """cleanup_temp_files deletes the .m3u8 playlist for the session."""
        session_id = "sess-abc-001"
        m3u8 = tmp_path / f"{session_id}.m3u8"
        m3u8.write_text("playlist")

        svc = _make_service(db_session)
        with patch(
            "pyrate.services.media.glob.glob",
            side_effect=lambda pattern: (
                [str(m3u8)] if ".m3u8" in pattern else []
            ),
        ):
            result = await svc.cleanup_temp_files(session_id)

        assert not m3u8.exists()
        assert result["temp_files_deleted"] == 1
        assert result["temp_files_failed"] == 0
        assert result["errors"] == []

    @pytest.mark.asyncio
    async def test_cleanup_deletes_ts_segments(
        self, db_session: AsyncSession, tmp_path: Path
    ):
        """cleanup_temp_files deletes all .ts segment files for the session."""
        session_id = "sess-ts-002"
        segments = [tmp_path / f"{session_id}_{i}.ts" for i in range(3)]
        for seg in segments:
            seg.write_bytes(b"data")

        svc = _make_service(db_session)
        with patch(
            "pyrate.services.media.glob.glob",
            side_effect=lambda pattern: (
                [] if ".m3u8" in pattern else [str(s) for s in segments]
            ),
        ):
            result = await svc.cleanup_temp_files(session_id)

        assert result["temp_files_deleted"] == 3
        assert all(not s.exists() for s in segments)

    @pytest.mark.asyncio
    async def test_cleanup_no_files_returns_zero(
        self, db_session: AsyncSession
    ):
        """cleanup_temp_files returns zero counts when no files match."""
        svc = _make_service(db_session)
        with patch(
            "pyrate.services.media.glob.glob", return_value=[]
        ):
            result = await svc.cleanup_temp_files("sess-empty")

        assert result["temp_files_deleted"] == 0
        assert result["temp_files_failed"] == 0
        assert result["errors"] == []

    @pytest.mark.asyncio
    async def test_cleanup_result_has_correct_keys(self, db_session: AsyncSession):
        """Return dict always contains the expected keys."""
        svc = _make_service(db_session)
        with patch("pyrate.services.media.glob.glob", return_value=[]):
            result = await svc.cleanup_temp_files("any-session")

        assert "temp_files_deleted" in result
        assert "temp_files_failed" in result
        assert "errors" in result

    @pytest.mark.asyncio
    async def test_cleanup_counts_failure_on_unlink_error(
        self, db_session: AsyncSession, tmp_path: Path
    ):
        """Files that cannot be deleted are counted in temp_files_failed."""
        session_id = "sess-fail-003"
        bad_file = tmp_path / f"{session_id}.m3u8"
        bad_file.write_text("x")

        svc = _make_service(db_session)
        with (
            patch(
                "pyrate.services.media.glob.glob",
                side_effect=lambda pattern: (
                    [str(bad_file)] if ".m3u8" in pattern else []
                ),
            ),
            patch.object(Path, "unlink", side_effect=OSError("Permission denied")),
        ):
            result = await svc.cleanup_temp_files(session_id)

        assert result["temp_files_failed"] == 1
        assert len(result["errors"]) == 1


# ---------------------------------------------------------------------------
# _cleanup_empty_dirs
# ---------------------------------------------------------------------------


class TestCleanupEmptyDirs:
    """Tests for MediaService._cleanup_empty_dirs()."""

    def test_removes_empty_directory(self, tmp_path: Path, db_session: AsyncSession):
        """An empty directory is removed."""
        empty_dir = tmp_path / "empty_subdir"
        empty_dir.mkdir()

        svc = _make_service(db_session)
        svc._cleanup_empty_dirs(empty_dir, stop_at=str(tmp_path))

        assert not empty_dir.exists()

    def test_removes_nested_empty_dirs(self, tmp_path: Path, db_session: AsyncSession):
        """Nested empty directories are removed up to the stop_at boundary."""
        nested = tmp_path / "level1" / "level2"
        nested.mkdir(parents=True)

        svc = _make_service(db_session)
        svc._cleanup_empty_dirs(nested, stop_at=str(tmp_path))

        assert not nested.exists()
        assert not (tmp_path / "level1").exists()

    def test_stops_at_non_empty_dir(self, tmp_path: Path, db_session: AsyncSession):
        """A non-empty directory is not removed."""
        parent = tmp_path / "parent"
        child = parent / "child"
        child.mkdir(parents=True)
        sibling = parent / "sibling.txt"
        sibling.write_text("keep me")

        svc = _make_service(db_session)
        svc._cleanup_empty_dirs(child, stop_at=str(tmp_path))

        assert not child.exists()  # empty child removed
        assert parent.exists()  # non-empty parent stays

    def test_stops_at_stop_at_boundary(self, tmp_path: Path, db_session: AsyncSession):
        """Directory matching stop_at is never removed."""
        boundary = tmp_path / "boundary"
        boundary.mkdir()

        svc = _make_service(db_session)
        svc._cleanup_empty_dirs(boundary, stop_at=str(boundary))

        # The boundary itself should remain
        assert boundary.exists()

    def test_nonexistent_dir_does_not_raise(self, tmp_path: Path, db_session: AsyncSession):
        """Passing a nonexistent path does not raise an exception."""
        svc = _make_service(db_session)
        svc._cleanup_empty_dirs(tmp_path / "nonexistent", stop_at=str(tmp_path))


# ---------------------------------------------------------------------------
# cleanup_orphaned_temp_files
# ---------------------------------------------------------------------------


class TestCleanupOrphanedTempFiles:
    """Tests for MediaService.cleanup_orphaned_temp_files()."""

    @pytest.mark.asyncio
    async def test_old_files_are_deleted(
        self, db_session: AsyncSession, tmp_path: Path
    ):
        """Files older than max_age_hours are deleted."""
        old_file = tmp_path / "old_session.ts"
        old_file.write_bytes(b"old")
        # Make the file look 3 hours old
        old_mtime = time.time() - 3 * 3600
        import os
        os.utime(old_file, (old_mtime, old_mtime))

        svc = _make_service(db_session)
        with patch(
            "pyrate.services.media.glob.glob",
            return_value=[str(old_file)],
        ):
            result = await svc.cleanup_orphaned_temp_files(max_age_hours=2)

        assert result["files_deleted"] == 1
        assert not old_file.exists()

    @pytest.mark.asyncio
    async def test_recent_files_are_kept(
        self, db_session: AsyncSession, tmp_path: Path
    ):
        """Files newer than max_age_hours are not deleted."""
        recent_file = tmp_path / "recent_session.ts"
        recent_file.write_bytes(b"recent")
        # File was just created — mtime is now

        svc = _make_service(db_session)
        with patch(
            "pyrate.services.media.glob.glob",
            return_value=[str(recent_file)],
        ):
            result = await svc.cleanup_orphaned_temp_files(max_age_hours=2)

        assert result["files_deleted"] == 0
        assert recent_file.exists()

    @pytest.mark.asyncio
    async def test_no_files_returns_zero_counts(self, db_session: AsyncSession):
        """When no temp files exist, all counts are zero."""
        svc = _make_service(db_session)
        with patch(
            "pyrate.services.media.glob.glob", return_value=[]
        ):
            result = await svc.cleanup_orphaned_temp_files()

        assert result["files_scanned"] == 0
        assert result["files_deleted"] == 0
        assert result["errors"] == []

    @pytest.mark.asyncio
    async def test_scanned_count_matches_glob_results(
        self, db_session: AsyncSession, tmp_path: Path
    ):
        """files_scanned equals the number of files returned by glob."""
        files = [tmp_path / f"seg_{i}.ts" for i in range(5)]
        for f in files:
            f.write_bytes(b"x")

        svc = _make_service(db_session)
        # cleanup_orphaned_temp_files calls glob twice: *.ts and *.m3u8
        # Return all 5 files on the first call (.ts), empty on the second (.m3u8)
        call_results = [[str(f) for f in files], []]
        with patch(
            "pyrate.services.media.glob.glob",
            side_effect=call_results,
        ):
            result = await svc.cleanup_orphaned_temp_files(max_age_hours=0)

        assert result["files_scanned"] == 5

    @pytest.mark.asyncio
    async def test_result_has_expected_keys(self, db_session: AsyncSession):
        """Return dict always has files_scanned, files_deleted, errors."""
        svc = _make_service(db_session)
        with patch("pyrate.services.media.glob.glob", return_value=[]):
            result = await svc.cleanup_orphaned_temp_files()

        assert "files_scanned" in result
        assert "files_deleted" in result
        assert "errors" in result


# ---------------------------------------------------------------------------
# cleanup_stream_on_stop (integration-style)
# ---------------------------------------------------------------------------


class TestCleanupStreamOnStop:
    """Tests for the cleanup_stream_on_stop convenience function."""

    @pytest.mark.asyncio
    async def test_returns_expected_structure(
        self, db_session: AsyncSession, tmp_path: Path
    ):
        """cleanup_stream_on_stop returns a dict with session_id, temp_cleanup, library_cleanup."""
        with patch("pyrate.services.media.glob.glob", return_value=[]):
            result = await cleanup_stream_on_stop(
                db=db_session,
                session_id="test-session-999",
                content_id=None,
                delete_library_file=False,
            )

        assert result["session_id"] == "test-session-999"
        assert "temp_cleanup" in result
        assert "library_cleanup" in result

    @pytest.mark.asyncio
    async def test_temp_files_cleaned_with_session(
        self, db_session: AsyncSession, tmp_path: Path
    ):
        """cleanup_stream_on_stop delegates temp cleanup to MediaService."""
        session_id = "stream-stop-abc"
        m3u8 = tmp_path / f"{session_id}.m3u8"
        m3u8.write_text("playlist")

        with patch(
            "pyrate.services.media.glob.glob",
            side_effect=lambda pattern: (
                [str(m3u8)] if ".m3u8" in pattern else []
            ),
        ):
            result = await cleanup_stream_on_stop(
                db=db_session,
                session_id=session_id,
                delete_library_file=False,
            )

        assert result["temp_cleanup"]["temp_files_deleted"] == 1
        assert not m3u8.exists()
