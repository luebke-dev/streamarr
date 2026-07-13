"""Tests for StorageCleanupService."""

import os
import time
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

# Set test environment before streamarr imports
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

from streamarr.services.storage_cleanup import StorageCleanupService, cleanup_session_temp_files


class TestDiskUsage:
    """Test disk usage monitoring."""

    def test_get_disk_usage_existing_path(self, tmp_path):
        """Test disk usage on an existing path."""
        result = StorageCleanupService.get_disk_usage(str(tmp_path))

        assert result["path"] == str(tmp_path)
        assert result["total"] > 0
        assert result["free"] > 0
        assert 0.0 <= result["usage_percent"] <= 100.0

    def test_get_disk_usage_nonexistent_path(self):
        """Test disk usage on a non-existent path."""
        result = StorageCleanupService.get_disk_usage("/nonexistent/path/xyz")

        assert result["total"] == 0
        assert result["used"] == 0
        assert result["free"] == 0
        assert result["usage_percent"] == 0.0

    def test_get_directory_size_empty(self, tmp_path):
        """Test directory size of an empty directory."""
        size = StorageCleanupService.get_directory_size(str(tmp_path))
        assert size == 0

    def test_get_directory_size_with_files(self, tmp_path):
        """Test directory size with files."""
        # Create some test files
        (tmp_path / "file1.txt").write_text("hello")
        (tmp_path / "file2.txt").write_text("world!!")
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        (subdir / "file3.txt").write_text("nested")

        size = StorageCleanupService.get_directory_size(str(tmp_path))
        assert size > 0

    def test_get_directory_size_nonexistent(self):
        """Test directory size of non-existent path."""
        size = StorageCleanupService.get_directory_size("/nonexistent/path")
        assert size == 0


class TestTranscodeTempCleanup:
    """Test transcoding temp file cleanup."""

    @pytest.mark.asyncio
    async def test_cleanup_empty_dir(self, tmp_path):
        """Test cleanup on empty directory."""
        service = StorageCleanupService()
        result = await service.cleanup_transcode_temp(
            temp_path=str(tmp_path), max_age_hours=1.0
        )

        assert result["files_scanned"] == 0
        assert result["files_deleted"] == 0
        assert result["bytes_freed"] == 0

    @pytest.mark.asyncio
    async def test_cleanup_nonexistent_dir(self):
        """Test cleanup on non-existent directory."""
        service = StorageCleanupService()
        result = await service.cleanup_transcode_temp(
            temp_path="/nonexistent/path", max_age_hours=1.0
        )

        assert result["files_scanned"] == 0
        assert result["files_deleted"] == 0

    @pytest.mark.asyncio
    async def test_cleanup_old_files(self, tmp_path):
        """Test that old files are deleted."""
        # Create old .ts files
        old_file = tmp_path / "session1_000.ts"
        old_file.write_bytes(b"\x00" * 1024)
        old_m3u8 = tmp_path / "session1.m3u8"
        old_m3u8.write_text("#EXTM3U")

        # Make them old (3 hours ago)
        old_time = time.time() - 3 * 3600
        os.utime(str(old_file), (old_time, old_time))
        os.utime(str(old_m3u8), (old_time, old_time))

        # Create fresh file
        fresh_file = tmp_path / "session2_000.ts"
        fresh_file.write_bytes(b"\x00" * 512)

        service = StorageCleanupService()
        result = await service.cleanup_transcode_temp(
            temp_path=str(tmp_path), max_age_hours=2.0
        )

        assert result["files_scanned"] == 3
        assert result["files_deleted"] == 2
        assert result["bytes_freed"] > 0

        # Old files should be gone
        assert not old_file.exists()
        assert not old_m3u8.exists()
        # Fresh file should remain
        assert fresh_file.exists()

    @pytest.mark.asyncio
    async def test_cleanup_by_size_limit(self, tmp_path):
        """Test cleanup when size limit is exceeded."""
        # Create multiple files
        for i in range(5):
            f = tmp_path / f"session_{i:03d}.ts"
            f.write_bytes(b"\x00" * (1024 * 100))  # 100KB each
            # Stagger modification times
            mtime = time.time() - (i * 60)
            os.utime(str(f), (mtime, mtime))

        service = StorageCleanupService()
        result = await service.cleanup_transcode_temp(
            temp_path=str(tmp_path),
            max_age_hours=24.0,  # Don't delete by age
            max_size_gb=0.0003,  # ~300KB limit (keep ~3 files)
        )

        assert result["files_scanned"] == 5
        assert result["files_deleted"] > 0
        assert result["bytes_freed"] > 0

    @pytest.mark.asyncio
    async def test_cleanup_ignores_non_ts_files(self, tmp_path):
        """Test that non-ts/m3u8 files are not touched."""
        # Create non-target files
        (tmp_path / "data.json").write_text("{}")
        (tmp_path / "readme.txt").write_text("keep")

        # Create old target file
        old_ts = tmp_path / "old_000.ts"
        old_ts.write_bytes(b"\x00" * 100)
        old_time = time.time() - 5 * 3600
        os.utime(str(old_ts), (old_time, old_time))

        service = StorageCleanupService()
        result = await service.cleanup_transcode_temp(
            temp_path=str(tmp_path), max_age_hours=1.0
        )

        assert result["files_scanned"] == 1  # Only .ts
        assert result["files_deleted"] == 1
        # Non-target files should remain
        assert (tmp_path / "data.json").exists()
        assert (tmp_path / "readme.txt").exists()


class TestCleanupSessionTempFiles:
    """Test the cleanup_session_temp_files helper."""

    def test_deletes_matching_files(self, tmp_path):
        """Test that m3u8 and ts files for the session are deleted."""
        sid = "abc123"
        m3u8 = tmp_path / f"{sid}.m3u8"
        m3u8.write_text("#EXTM3U")
        ts0 = tmp_path / f"{sid}_000.ts"
        ts0.write_bytes(b"\x00" * 100)
        ts1 = tmp_path / f"{sid}_001.ts"
        ts1.write_bytes(b"\x00" * 100)

        # Unrelated file should not be touched
        other = tmp_path / "other_session_000.ts"
        other.write_bytes(b"\x00" * 50)

        result = cleanup_session_temp_files(sid, temp_path=str(tmp_path))

        assert result["deleted"] == 3
        assert result["errors"] == 0
        assert not m3u8.exists()
        assert not ts0.exists()
        assert not ts1.exists()
        assert other.exists()

    def test_no_matching_files(self, tmp_path):
        """Test with no matching files returns zero counts."""
        result = cleanup_session_temp_files("nonexistent", temp_path=str(tmp_path))
        assert result["deleted"] == 0
        assert result["errors"] == 0

    def test_nonexistent_temp_path(self):
        """Test with a temp path that does not exist."""
        result = cleanup_session_temp_files("abc", temp_path="/nonexistent/dir")
        assert result["deleted"] == 0
        assert result["errors"] == 0


class TestDownloadRecordsCleanup:
    """Test download record cleanup."""

    @pytest.mark.asyncio
    async def test_cleanup_without_db(self):
        """Test cleanup without database session returns error."""
        service = StorageCleanupService(db=None)
        result = await service.cleanup_old_downloads(max_age_days=30)

        assert result["records_deleted"] == 0
        assert "error" in result


class TestOrphanedFileCleanup:
    """Test orphaned media file cleanup."""

    @pytest.mark.asyncio
    async def test_cleanup_without_db(self):
        """Test cleanup without database session returns error."""
        service = StorageCleanupService(db=None)
        result = await service.cleanup_orphaned_media_files()

        assert result["records_cleaned"] == 0
        assert "error" in result


class TestDuplicateCleanup:
    """Test duplicate media file cleanup."""

    @pytest.mark.asyncio
    async def test_cleanup_without_db(self):
        """Test cleanup without database session returns error."""
        service = StorageCleanupService(db=None)
        result = await service.cleanup_library_duplicates(
            library_path="/library/movies"
        )

        assert result["duplicates_removed"] == 0
        assert "error" in result


class TestStorageOverview:
    """Test storage overview."""

    @pytest.mark.asyncio
    async def test_overview(self, tmp_path):
        """Test storage overview returns all sections."""
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()
        lib_dir = tmp_path / "library"
        lib_dir.mkdir()

        service = StorageCleanupService()
        overview = await service.get_storage_overview(
            temp_path=str(temp_dir),
            library_paths=[str(lib_dir)],
        )

        assert "temp" in overview
        assert overview["temp"]["total"] > 0
        assert "libraries" in overview


class TestFullCleanup:
    """Test full cleanup run."""

    @pytest.mark.asyncio
    async def test_full_cleanup_without_db(self, tmp_path):
        """Test full cleanup without DB only does temp cleanup."""
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()

        # Create an old temp file
        old_ts = temp_dir / "old_000.ts"
        old_ts.write_bytes(b"\x00" * 256)
        old_time = time.time() - 5 * 3600
        os.utime(str(old_ts), (old_time, old_time))

        service = StorageCleanupService(db=None)
        result = await service.run_full_cleanup(
            temp_path=str(temp_dir),
            temp_max_age_hours=1.0,
            library_paths=[],
        )

        assert result["temp_cleanup"]["files_deleted"] == 1
        assert not old_ts.exists()


# =========================================================================
# DB integration tests (using db_session fixture from conftest.py)
# =========================================================================


class TestDownloadRecordsCleanupDB:
    """Test cleanup_old_downloads with a real DB session."""

    @pytest.mark.asyncio
    async def test_deletes_old_completed_downloads(self, db_session: AsyncSession):
        from datetime import datetime, timedelta, UTC

        from streamarr.models.downloader import Downloader
        from streamarr.models.downloads import Download

        downloader = Downloader(
            guid=uuid.uuid4(),
            label="Test",
            type="sabnzbd",
            host="http://localhost",
            api_key="key",
        )
        db_session.add(downloader)
        await db_session.flush()

        # Create an old "Imported" download (>30 days)
        old = Download(
            guid=uuid.uuid4(),
            title="Old Movie",
            type="movie",
            downloader_id=downloader.guid,
            status="Imported",
            external_id="nzo_old",
            created_at=datetime.now(UTC) - timedelta(days=60),
        )
        db_session.add(old)

        # Create a recent "Imported" download
        recent = Download(
            guid=uuid.uuid4(),
            title="Recent Movie",
            type="movie",
            downloader_id=downloader.guid,
            status="Imported",
            external_id="nzo_recent",
            created_at=datetime.now(UTC) - timedelta(days=5),
        )
        db_session.add(recent)

        # Create an old "queued" download (should not be deleted)
        old_queued = Download(
            guid=uuid.uuid4(),
            title="Queued Movie",
            type="movie",
            downloader_id=downloader.guid,
            status="queued",
            external_id="nzo_queued",
            created_at=datetime.now(UTC) - timedelta(days=60),
        )
        db_session.add(old_queued)
        await db_session.commit()

        service = StorageCleanupService(db=db_session)
        result = await service.cleanup_old_downloads(max_age_days=30)

        assert result["records_deleted"] == 1

    @pytest.mark.asyncio
    async def test_custom_statuses(self, db_session: AsyncSession):
        from datetime import datetime, timedelta, UTC

        from streamarr.models.downloader import Downloader
        from streamarr.models.downloads import Download

        downloader = Downloader(
            guid=uuid.uuid4(),
            label="Test2",
            type="sabnzbd",
            host="http://localhost",
            api_key="key2",
        )
        db_session.add(downloader)
        await db_session.flush()

        old_failed = Download(
            guid=uuid.uuid4(),
            title="Failed Movie",
            type="movie",
            downloader_id=downloader.guid,
            status="Failed",
            external_id="nzo_fail",
            created_at=datetime.now(UTC) - timedelta(days=60),
        )
        db_session.add(old_failed)
        await db_session.commit()

        service = StorageCleanupService(db=db_session)
        result = await service.cleanup_old_downloads(
            max_age_days=30, statuses=["Failed"]
        )
        assert result["records_deleted"] == 1


class TestOrphanedMediaFilesCleanupDB:
    """Test cleanup_orphaned_media_files with a real DB session."""

    @pytest.mark.asyncio
    async def test_removes_orphaned_records(self, db_session: AsyncSession, tmp_path):
        from streamarr.models.media import MediaFile, MediaItem, MediaType

        item = MediaItem(
            guid=uuid.uuid4(),
            title="Test Item",
            media_type=MediaType.MOVIES,
        )
        db_session.add(item)
        await db_session.flush()

        # Orphaned record: file doesn't exist on disk
        orphan = MediaFile(
            guid=uuid.uuid4(),
            media_item_guid=item.guid,
            file_path="/nonexistent/path/movie.mkv",
            file_size=1000,
            codec="h264",
            width=1920,
            height=1080,
        )
        db_session.add(orphan)

        # Valid record: file exists on disk
        valid_file = tmp_path / "valid.mkv"
        valid_file.write_bytes(b"\x00" * 100)
        valid = MediaFile(
            guid=uuid.uuid4(),
            media_item_guid=item.guid,
            file_path=str(valid_file),
            file_size=100,
            codec="h264",
            width=1920,
            height=1080,
        )
        db_session.add(valid)
        await db_session.commit()

        service = StorageCleanupService(db=db_session)
        result = await service.cleanup_orphaned_media_files()

        assert result["files_checked"] == 2
        assert result["orphaned_records"] == 1

    @pytest.mark.asyncio
    async def test_no_orphans(self, db_session: AsyncSession, tmp_path):
        from streamarr.models.media import MediaFile, MediaItem, MediaType

        item = MediaItem(
            guid=uuid.uuid4(),
            title="Valid Item",
            media_type=MediaType.MOVIES,
        )
        db_session.add(item)
        await db_session.flush()

        valid_file = tmp_path / "exists.mkv"
        valid_file.write_bytes(b"\x00" * 50)

        mf = MediaFile(
            guid=uuid.uuid4(),
            media_item_guid=item.guid,
            file_path=str(valid_file),
            file_size=50,
            codec="h264",
            width=1920,
            height=1080,
        )
        db_session.add(mf)
        await db_session.commit()

        service = StorageCleanupService(db=db_session)
        result = await service.cleanup_orphaned_media_files()

        assert result["files_checked"] == 1
        assert result["orphaned_records"] == 0


class TestLibraryDuplicatesCleanupDB:
    """Test cleanup_library_duplicates with a real DB session."""

    @pytest.mark.asyncio
    async def test_removes_duplicates_keeps_largest(
        self, db_session: AsyncSession, tmp_path
    ):
        from streamarr.models.media import MediaFile, MediaItem, MediaType

        item = MediaItem(
            guid=uuid.uuid4(),
            title="Dup Item",
            media_type=MediaType.MOVIES,
        )
        db_session.add(item)
        await db_session.flush()

        lib_path = tmp_path / "library" / "movies"
        lib_path.mkdir(parents=True)

        # Create two files for the same media item
        big_file = lib_path / "movie_1080p.mkv"
        big_file.write_bytes(b"\x00" * 2000)
        small_file = lib_path / "movie_720p.mkv"
        small_file.write_bytes(b"\x00" * 500)

        mf1 = MediaFile(
            guid=uuid.uuid4(),
            media_item_guid=item.guid,
            file_path=str(big_file),
            file_size=2000,
            codec="h264",
            width=1920,
            height=1080,
        )
        mf2 = MediaFile(
            guid=uuid.uuid4(),
            media_item_guid=item.guid,
            file_path=str(small_file),
            file_size=500,
            codec="h264",
            width=1280,
            height=720,
        )
        db_session.add_all([mf1, mf2])
        await db_session.commit()

        service = StorageCleanupService(db=db_session)
        result = await service.cleanup_library_duplicates(
            library_path=str(lib_path), keep_newest=True
        )

        assert result["items_checked"] == 1
        assert result["duplicates_removed"] == 1
        assert result["bytes_freed"] == 500
        # Larger file should still exist
        assert big_file.exists()
        assert not small_file.exists()

    @pytest.mark.asyncio
    async def test_no_duplicates(self, db_session: AsyncSession, tmp_path):
        from streamarr.models.media import MediaFile, MediaItem, MediaType

        item = MediaItem(
            guid=uuid.uuid4(),
            title="Single Item",
            media_type=MediaType.MOVIES,
        )
        db_session.add(item)
        await db_session.flush()

        lib_path = tmp_path / "library" / "movies"
        lib_path.mkdir(parents=True)

        single_file = lib_path / "movie.mkv"
        single_file.write_bytes(b"\x00" * 1000)

        mf = MediaFile(
            guid=uuid.uuid4(),
            media_item_guid=item.guid,
            file_path=str(single_file),
            file_size=1000,
            codec="h264",
            width=1920,
            height=1080,
        )
        db_session.add(mf)
        await db_session.commit()

        service = StorageCleanupService(db=db_session)
        result = await service.cleanup_library_duplicates(library_path=str(lib_path))

        assert result["items_checked"] == 1
        assert result["duplicates_removed"] == 0
