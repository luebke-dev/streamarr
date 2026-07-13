"""Tests for backup endpoints (/api/backups/*)."""

import uuid
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.models.media import AvailabilityStatus, MediaFile, MediaItem, MediaType
from streamarr.models.setting import Setting
from streamarr.models.user import User


async def _create_media_item(db: AsyncSession, **overrides) -> MediaItem:
    defaults = dict(
        guid=uuid.uuid4(),
        title="Backup Movie",
        media_type=MediaType.MOVIES,
        availability_status=AvailabilityStatus.UNKNOWN,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    item = MediaItem(**defaults)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


class TestSettingsBackup:
    async def test_export_requires_auth(self, client: AsyncClient):
        resp = await client.get("/api/backups/settings")
        assert resp.status_code == 401

    async def test_export_forbidden_for_regular_user(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get("/api/backups/settings", headers=user_headers)
        assert resp.status_code == 403

    async def test_export_redacts_secrets_by_default(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        await client.put(
            "/api/settings/subtitles",
            headers=admin_headers,
            json={"subtitle_providers": ["opensubtitles"]},
        )
        resp = await client.get("/api/backups/settings", headers=admin_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["backup_type"] == "settings"
        assert data["include_defaults"] is True
        assert data["include_secrets"] is False
        assert data["settings"]["oidc.jwt_secret_key"] == "[redacted]"
        assert data["settings"]["subtitles.providers"] == ["opensubtitles"]

    async def test_export_can_include_secrets(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.get(
            "/api/backups/settings",
            headers=admin_headers,
            params={"include_secrets": "true"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["include_secrets"] is True
        assert data["settings"]["plugin.tmdb.api_key"] is None

    async def test_export_stored_only(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        await client.put(
            "/api/settings/system",
            headers=admin_headers,
            json={"site_name": "Stored Only"},
        )

        resp = await client.get(
            "/api/backups/settings",
            headers=admin_headers,
            params={"include_defaults": "false"},
        )

        assert resp.status_code == 200
        settings = resp.json()["settings"]
        assert settings["system.site_name"] == "Stored Only"
        assert "system.locale" not in settings

    async def test_restore_settings_skips_redacted_values(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.post(
            "/api/backups/settings/restore",
            headers=admin_headers,
            json={
                "settings": {
                    "system.site_name": "Restored Name",
                    "plugin.tmdb.api_key": "[redacted]",
                }
            },
        )

        assert resp.status_code == 200
        assert resp.json() == {"restored_count": 1, "skipped_count": 1}

        system = await client.get("/api/settings/system", headers=admin_headers)
        assert system.json()["site_name"] == "Restored Name"

        logs = await client.get(
            "/api/activity-logs",
            headers=admin_headers,
            params={"event_type": "settings.restore"},
        )
        assert logs.status_code == 200
        assert logs.json()["total"] >= 1

    async def test_restore_settings_can_write_redacted_literal_when_requested(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.post(
            "/api/backups/settings/restore",
            headers=admin_headers,
            json={
                "skip_redacted": False,
                "settings": {"system.site_name": "[redacted]"},
            },
        )

        assert resp.status_code == 200
        assert resp.json()["restored_count"] == 1
        system = await client.get("/api/settings/system", headers=admin_headers)
        assert system.json()["site_name"] == "[redacted]"


class TestDatabaseBackup:
    async def test_export_database_requires_admin(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get("/api/backups/database", headers=user_headers)
        assert resp.status_code == 403

    async def test_export_database_redacts_settings_secrets(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        await client.put(
            "/api/settings/system",
            headers=admin_headers,
            json={"site_name": "Backup Site"},
        )

        resp = await client.get("/api/backups/database", headers=admin_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["backup_type"] == "database"
        assert data["include_secrets"] is False
        assert "settings" in data["tables"]
        settings_rows = data["tables"]["settings"]
        assert any(row["key"] == "system.site_name" for row in settings_rows)

        logs = await client.get(
            "/api/activity-logs",
            headers=admin_headers,
            params={"event_type": "backup.database_export"},
        )
        assert logs.status_code == 200
        assert logs.json()["total"] >= 1

    async def test_export_database_limit_marks_truncated(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.get(
            "/api/backups/database",
            headers=admin_headers,
            params={"limit_per_table": 1},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["limit_per_table"] == 1
        assert isinstance(data["truncated_tables"], list)

    async def test_database_restore_dry_run_counts_rows(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        row_id = uuid.uuid4()

        resp = await client.post(
            "/api/backups/database/restore",
            headers=admin_headers,
            json={
                "dry_run": True,
                "tables": {
                    "settings": [
                        {
                            "id": str(row_id),
                            "key": "restore.database.dry_run",
                            "value": "planned",
                            "created_at": datetime.now(UTC).isoformat(),
                            "updated_at": datetime.now(UTC).isoformat(),
                        }
                    ]
                },
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["dry_run"] is True
        assert data["restored_rows"] == 1
        assert data["table_counts"]["settings"] == 1

    async def test_database_restore_upserts_rows(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_superuser: User,
        admin_headers,
    ):
        row_id = uuid.uuid4()

        resp = await client.post(
            "/api/backups/database/restore",
            headers=admin_headers,
            json={
                "dry_run": False,
                "tables": {
                    "settings": [
                        {
                            "id": str(row_id),
                            "key": "restore.database.real",
                            "value": "restored",
                            "created_at": datetime.now(UTC).isoformat(),
                            "updated_at": datetime.now(UTC).isoformat(),
                        }
                    ]
                },
            },
        )

        assert resp.status_code == 200
        assert resp.json()["restored_rows"] == 1
        restored = await db_session.get(Setting, row_id)
        assert restored is not None
        assert restored.key == "restore.database.real"
        assert restored.value == "restored"

        logs = await client.get(
            "/api/activity-logs",
            headers=admin_headers,
            params={"event_type": "backup.database_restore"},
        )
        assert logs.status_code == 200
        assert logs.json()["total"] >= 1

    async def test_database_restore_skips_redacted_secrets(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.post(
            "/api/backups/database/restore",
            headers=admin_headers,
            json={
                "dry_run": True,
                "tables": {
                    "settings": [
                        {
                            "id": str(uuid.uuid4()),
                            "key": "plugin.tmdb.api_key",
                            "value": "[redacted]",
                        }
                    ]
                },
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["restored_rows"] == 0
        assert data["skipped_rows"] == 1

    async def test_database_restore_delete_missing_rows_requires_confirmation(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.post(
            "/api/backups/database/restore",
            headers=admin_headers,
            json={
                "dry_run": False,
                "delete_missing_rows": True,
                "delete_missing_tables": ["settings"],
                "tables": {"settings": []},
            },
        )

        assert resp.status_code == 400

    async def test_database_restore_delete_missing_rows_dry_run(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_superuser: User,
        admin_headers,
    ):
        keep_id = uuid.uuid4()
        delete_id = uuid.uuid4()
        db_session.add_all(
            [
                Setting(id=keep_id, key="restore.keep", value="keep"),
                Setting(id=delete_id, key="restore.delete", value="delete"),
            ]
        )
        await db_session.commit()

        resp = await client.post(
            "/api/backups/database/restore",
            headers=admin_headers,
            json={
                "dry_run": True,
                "delete_missing_rows": True,
                "delete_missing_tables": ["settings"],
                "tables": {
                    "settings": [
                        {
                            "id": str(keep_id),
                            "key": "restore.keep",
                            "value": "keep",
                        }
                    ]
                },
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["deleted_rows"] >= 1
        assert data["deleted_table_counts"]["settings"] >= 1
        assert await db_session.get(Setting, delete_id) is not None

    async def test_database_restore_delete_missing_rows_real_run(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_superuser: User,
        admin_headers,
    ):
        keep_id = uuid.uuid4()
        delete_id = uuid.uuid4()
        db_session.add_all(
            [
                Setting(id=keep_id, key="restore.keep.real", value="keep"),
                Setting(id=delete_id, key="restore.delete.real", value="delete"),
            ]
        )
        await db_session.commit()

        resp = await client.post(
            "/api/backups/database/restore",
            headers=admin_headers,
            json={
                "dry_run": False,
                "delete_missing_rows": True,
                "delete_missing_tables": ["settings"],
                "destructive_confirmation": "DELETE_MISSING_ROWS",
                "tables": {
                    "settings": [
                        {
                            "id": str(keep_id),
                            "key": "restore.keep.real",
                            "value": "keep",
                        }
                    ]
                },
            },
        )

        assert resp.status_code == 200
        assert resp.json()["deleted_rows"] >= 1
        assert await db_session.get(Setting, delete_id) is None


class TestMediaManifestBackup:
    async def test_media_manifest_requires_admin(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get("/api/backups/media-manifest", headers=user_headers)
        assert resp.status_code == 403

    async def test_export_media_manifest(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_superuser: User,
        admin_headers,
        tmp_path,
    ):
        item = await _create_media_item(db_session)
        media_path = tmp_path / "movie.mkv"
        media_path.write_bytes(b"movie")
        media_file = MediaFile(
            guid=uuid.uuid4(),
            media_item_guid=item.guid,
            file_path=str(media_path),
            file_name="movie.mkv",
            file_size=5,
            quality="1080p",
            format="mkv",
        )
        db_session.add(media_file)
        await db_session.commit()

        resp = await client.get(
            "/api/backups/media-manifest",
            headers=admin_headers,
            params={"check_exists": "true"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["backup_type"] == "media_manifest"
        assert data["total_files"] == 1
        assert data["total_bytes"] == 5
        assert data["missing_files"] == 0
        assert data["files"][0]["file_path"] == str(media_path)
        assert data["files"][0]["exists"] is True

        logs = await client.get(
            "/api/activity-logs",
            headers=admin_headers,
            params={"event_type": "backup.media_manifest_export"},
        )
        assert logs.status_code == 200
        assert logs.json()["total"] >= 1

    async def test_export_media_manifest_marks_missing_files(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_superuser: User,
        admin_headers,
    ):
        item = await _create_media_item(db_session)
        db_session.add(
            MediaFile(
                guid=uuid.uuid4(),
                media_item_guid=item.guid,
                file_path="/definitely/missing/movie.mkv",
                file_name="movie.mkv",
            )
        )
        await db_session.commit()

        resp = await client.get(
            "/api/backups/media-manifest",
            headers=admin_headers,
            params={"check_exists": "true"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["missing_files"] == 1
        assert data["files"][0]["exists"] is False

    async def test_media_manifest_copy_dry_run(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_superuser: User,
        admin_headers,
        tmp_path,
    ):
        item = await _create_media_item(db_session)
        source = tmp_path / "source.mkv"
        destination = tmp_path / "backup"
        source.write_bytes(b"movie")
        media_file_guid = uuid.uuid4()

        resp = await client.post(
            "/api/backups/media-manifest/copy",
            headers=admin_headers,
            json={
                "destination_root": str(destination),
                "dry_run": True,
                "files": [
                    {
                        "media_file_guid": str(media_file_guid),
                        "media_item_guid": str(item.guid),
                        "title": item.title,
                        "media_type": item.media_type.value,
                        "file_path": str(source),
                        "file_name": "source.mkv",
                        "file_size": 5,
                    }
                ],
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["dry_run"] is True
        assert data["planned_count"] == 1
        assert data["copied_count"] == 0
        assert not destination.exists()

    async def test_media_manifest_copy_files(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_superuser: User,
        admin_headers,
        tmp_path,
    ):
        item = await _create_media_item(db_session)
        source = tmp_path / "source.mkv"
        destination = tmp_path / "backup"
        source.write_bytes(b"movie")
        media_file_guid = uuid.uuid4()

        resp = await client.post(
            "/api/backups/media-manifest/copy",
            headers=admin_headers,
            json={
                "destination_root": str(destination),
                "dry_run": False,
                "files": [
                    {
                        "media_file_guid": str(media_file_guid),
                        "media_item_guid": str(item.guid),
                        "title": item.title,
                        "media_type": item.media_type.value,
                        "file_path": str(source),
                        "file_name": "source.mkv",
                        "file_size": 5,
                    }
                ],
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["copied_count"] == 1
        copied_path = data["items"][0]["destination_path"]
        assert copied_path.endswith(f"{item.guid}/source.mkv")
        assert (destination / "movies" / str(item.guid) / "source.mkv").read_bytes() == b"movie"

        logs = await client.get(
            "/api/activity-logs",
            headers=admin_headers,
            params={"event_type": "backup.media_manifest_copy"},
        )
        assert logs.status_code == 200
        assert logs.json()["total"] >= 1

    async def test_media_manifest_copy_marks_missing_files(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_superuser: User,
        admin_headers,
        tmp_path,
    ):
        item = await _create_media_item(db_session)

        resp = await client.post(
            "/api/backups/media-manifest/copy",
            headers=admin_headers,
            json={
                "destination_root": str(tmp_path / "backup"),
                "dry_run": False,
                "files": [
                    {
                        "media_file_guid": str(uuid.uuid4()),
                        "media_item_guid": str(item.guid),
                        "file_path": str(tmp_path / "missing.mkv"),
                        "file_name": "missing.mkv",
                    }
                ],
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["missing_count"] == 1
        assert data["items"][0]["status"] == "missing"
