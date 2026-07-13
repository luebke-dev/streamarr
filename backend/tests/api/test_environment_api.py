"""Tests for environment API endpoints (/api/environment/*)."""

from pathlib import Path

from httpx import AsyncClient

from streamarr.models.user import User


class TestEnvironmentPaths:
    async def test_paths_requires_auth(self, client: AsyncClient):
        resp = await client.get("/api/environment/paths")
        assert resp.status_code == 401

    async def test_paths_forbidden_for_regular_user(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get("/api/environment/paths", headers=user_headers)
        assert resp.status_code == 403

    async def test_paths_for_admin(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.get("/api/environment/paths", headers=admin_headers)

        assert resp.status_code == 200
        data = resp.json()
        keys = {row["key"] for row in data}
        assert "cwd" in keys
        assert "transcoding_temp" in keys
        assert "database_url" not in keys
        assert all("readable" in row and "writable" in row for row in data)


class TestEnvironmentDirectory:
    async def test_directory_requires_admin(self, client: AsyncClient, user_headers):
        resp = await client.get(
            "/api/environment/directory",
            headers=user_headers,
            params={"path": "/tmp"},
        )
        assert resp.status_code == 403

    async def test_lists_directory(
        self,
        client: AsyncClient,
        test_superuser: User,
        admin_headers,
        tmp_path: Path,
    ):
        visible = tmp_path / "visible.txt"
        visible.write_text("hello")
        hidden = tmp_path / ".hidden.txt"
        hidden.write_text("secret")
        nested = tmp_path / "nested"
        nested.mkdir()

        resp = await client.get(
            "/api/environment/directory",
            headers=admin_headers,
            params={"path": str(tmp_path)},
        )

        assert resp.status_code == 200
        data = resp.json()
        names = [entry["name"] for entry in data["entries"]]
        assert "nested" in names
        assert "visible.txt" in names
        assert ".hidden.txt" not in names

    async def test_can_include_hidden_entries(
        self,
        client: AsyncClient,
        test_superuser: User,
        admin_headers,
        tmp_path: Path,
    ):
        hidden = tmp_path / ".hidden.txt"
        hidden.write_text("secret")

        resp = await client.get(
            "/api/environment/directory",
            headers=admin_headers,
            params={"path": str(tmp_path), "include_hidden": "true"},
        )

        assert resp.status_code == 200
        names = [entry["name"] for entry in resp.json()["entries"]]
        assert ".hidden.txt" in names

    async def test_missing_directory_returns_404(
        self,
        client: AsyncClient,
        test_superuser: User,
        admin_headers,
        tmp_path: Path,
    ):
        resp = await client.get(
            "/api/environment/directory",
            headers=admin_headers,
            params={"path": str(tmp_path / "missing")},
        )

        assert resp.status_code == 404


class TestEnvironmentDirectoryTools:
    async def test_directory_contents_requires_admin(self, client: AsyncClient, user_headers):
        resp = await client.get(
            "/api/environment/directory-contents",
            headers=user_headers,
            params={"path": "/tmp", "include_directories": "true"},
        )
        assert resp.status_code == 403

    async def test_directory_contents_filters_entries(
        self,
        client: AsyncClient,
        test_superuser: User,
        admin_headers,
        tmp_path: Path,
    ):
        (tmp_path / "nested").mkdir()
        (tmp_path / "file.txt").write_text("hello")

        resp = await client.get(
            "/api/environment/directory-contents",
            headers=admin_headers,
            params={
                "path": str(tmp_path),
                "include_files": "false",
                "include_directories": "true",
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert [entry["name"] for entry in data] == ["nested"]
        assert data[0]["type"] == "Directory"

    async def test_validate_path_and_parent_path(
        self,
        client: AsyncClient,
        test_superuser: User,
        admin_headers,
        tmp_path: Path,
    ):
        target = tmp_path / "file.txt"
        target.write_text("hello")

        validate = await client.post(
            "/api/environment/validate-path",
            headers=admin_headers,
            json={"path": str(target), "is_file": True},
        )
        parent = await client.get(
            "/api/environment/parent-path",
            headers=admin_headers,
            params={"path": str(target)},
        )

        assert validate.status_code == 204
        assert parent.status_code == 200
        assert parent.json() == str(tmp_path)

    async def test_drives_and_default_directory_browser(
        self,
        client: AsyncClient,
        test_superuser: User,
        admin_headers,
    ):
        drives = await client.get("/api/environment/drives", headers=admin_headers)
        default_directory = await client.get(
            "/api/environment/default-directory",
            headers=admin_headers,
        )

        assert drives.status_code == 200
        assert drives.json()[0]["path"] == "/"
        assert default_directory.status_code == 200
        assert default_directory.json()["path"] == "/"
