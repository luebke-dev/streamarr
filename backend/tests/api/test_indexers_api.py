"""Tests for the indexers API endpoints."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from pyrate.models.indexer import Indexer

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helper: create an indexer in the test DB
# ---------------------------------------------------------------------------
async def _create_indexer(db_session, label="Test Indexer", indexer_type="newznab") -> Indexer:
    indexer = Indexer(
        guid=uuid.uuid4(),
        label=label,
        host="https://indexer.example.com",
        api_key="test-api-key",
        type=indexer_type,
        ssl=True,
        verify_ssl=True,
    )
    db_session.add(indexer)
    await db_session.commit()
    await db_session.refresh(indexer)
    return indexer


# ---------------------------------------------------------------------------
# GET /api/indexers/types
# ---------------------------------------------------------------------------
class TestListIndexerTypes:
    async def test_list_indexer_types(self, client: AsyncClient, admin_headers):
        """Returns the native indexer types exposed by the API."""
        resp = await client.get("/api/indexers/types", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        by_domain = {entry["domain"]: entry for entry in data}
        assert set(by_domain) == {"newznab", "torznab"}
        assert by_domain["newznab"]["name"] == "Newznab"
        assert by_domain["torznab"]["description"] == "Torznab-compatible torrent indexer"
        assert by_domain["newznab"]["config_schema"] == {}

    async def test_list_indexer_types_is_static(
        self, client: AsyncClient, admin_headers
    ):
        """The native indexer list does not depend on plugin registry state."""
        resp = await client.get("/api/indexers/types", headers=admin_headers)
        assert resp.status_code == 200
        assert [entry["domain"] for entry in resp.json()] == ["newznab", "torznab"]

    async def test_list_indexer_types_unauthenticated(self, client: AsyncClient):
        resp = await client.get("/api/indexers/types")
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/indexers/validate
# ---------------------------------------------------------------------------
class TestValidateIndexerConfig:
    async def test_validate_plugin_not_found(self, client: AsyncClient, admin_headers):
        """Returns valid=False when the native indexer type is not known."""
        resp = await client.post(
            "/api/indexers/validate?plugin_type=nonexistent",
            json={"host": "https://example.com"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        assert "Unknown indexer type" in data["errors"][0]

    async def test_validate_plugin_not_indexer(self, client: AsyncClient, admin_headers):
        """Returns valid=False for non-native indexer types."""
        resp = await client.post(
            "/api/indexers/validate?plugin_type=somedl",
            json={},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        assert "Unknown indexer type" in data["errors"][0]

    async def test_validate_success(self, client: AsyncClient, admin_headers):
        """Returns validation result from the native indexer instance."""
        mock_instance = MagicMock()
        mock_instance.validate_config = AsyncMock(return_value={"valid": True, "errors": []})
        mock_instance.close = AsyncMock()

        with patch("pyrate.indexers.newznab.Newznab", return_value=mock_instance) as cls:
            resp = await client.post(
                "/api/indexers/validate?plugin_type=newznab",
                json={"host": "https://example.com", "api_key": "secret"},
                headers=admin_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        cls.assert_called_once_with(host="https://example.com", api_key="secret")
        mock_instance.validate_config.assert_awaited_once_with(
            {"host": "https://example.com", "api_key": "secret"}
        )
        mock_instance.close.assert_awaited_once()

    async def test_validate_exception_returns_error(self, client: AsyncClient, admin_headers):
        """Returns valid=False with error message when an unexpected exception occurs."""
        mock_instance = MagicMock()
        mock_instance.validate_config = AsyncMock(side_effect=RuntimeError("boom"))
        mock_instance.close = AsyncMock()

        with patch("pyrate.indexers.newznab.Newznab", return_value=mock_instance):
            resp = await client.post(
                "/api/indexers/validate?plugin_type=newznab",
                json={},
                headers=admin_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        assert "Validation error" in data["errors"][0]
        mock_instance.close.assert_awaited_once()

    async def test_validate_unauthenticated(self, client: AsyncClient):
        resp = await client.post(
            "/api/indexers/validate?plugin_type=newznab", json={}
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/indexers/caps
# ---------------------------------------------------------------------------
class TestGetIndexerCaps:
    def _make_mock_http_client(self, response):
        """Helper: build a mock httpx AsyncClient context manager."""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=response)
        return mock_client

    async def test_caps_success_with_subcategories(
        self, client: AsyncClient, admin_headers
    ):
        """Returns connected=True with parsed categories and subcategories."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "channel": {
                "categories": {
                    "category": [
                        {
                            "@attributes": {"id": "2000", "name": "Movies"},
                            "subcat": [
                                {"@attributes": {"id": "2010", "name": "Movies/HD"}}
                            ],
                        }
                    ]
                }
            }
        }
        mock_http = self._make_mock_http_client(mock_resp)
        with patch("httpx.AsyncClient", return_value=mock_http):
            resp = await client.post(
                "/api/indexers/caps",
                json={"host": "https://indexer.example.com", "api_key": "abc"},
                headers=admin_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is True
        assert len(data["categories"]) == 1
        assert data["categories"][0]["name"] == "Movies"
        assert data["categories"][0]["subcategories"][0]["name"] == "Movies/HD"

    async def test_caps_host_without_protocol_ssl(
        self, client: AsyncClient, admin_headers
    ):
        """Prepends https:// when ssl=True and no protocol prefix in host."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"channel": {"categories": {}}}
        mock_http = self._make_mock_http_client(mock_resp)
        with patch("httpx.AsyncClient", return_value=mock_http):
            resp = await client.post(
                "/api/indexers/caps",
                json={"host": "indexer.example.com", "api_key": "abc", "ssl": True},
                headers=admin_headers,
            )
        assert resp.status_code == 200
        assert resp.json()["connected"] is True

    async def test_caps_host_without_protocol_no_ssl(
        self, client: AsyncClient, admin_headers
    ):
        """Prepends http:// when ssl=False and no protocol prefix in host."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {"channel": {"categories": {}}}
        mock_http = self._make_mock_http_client(mock_resp)
        with patch("httpx.AsyncClient", return_value=mock_http):
            resp = await client.post(
                "/api/indexers/caps",
                json={"host": "indexer.local", "api_key": "abc", "ssl": False},
                headers=admin_headers,
            )
        assert resp.status_code == 200
        assert resp.json()["connected"] is True

    async def test_caps_timeout(self, client: AsyncClient, admin_headers):
        """Returns connected=False with timeout error message on TimeoutException."""
        import httpx

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)
        mock_http.get = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
        with patch("httpx.AsyncClient", return_value=mock_http):
            resp = await client.post(
                "/api/indexers/caps",
                json={"host": "https://slow.indexer.com", "api_key": "abc"},
                headers=admin_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is False
        assert data["error"] == "Connection timed out"

    async def test_caps_http_status_error(self, client: AsyncClient, admin_headers):
        """Returns connected=False with HTTP error details on HTTPStatusError."""
        import httpx

        mock_http_response = MagicMock()
        mock_http_response.status_code = 403
        mock_http_response.text = "Forbidden"

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)
        mock_http.get = AsyncMock(
            side_effect=httpx.HTTPStatusError(
                "403 Forbidden", request=MagicMock(), response=mock_http_response
            )
        )
        with patch("httpx.AsyncClient", return_value=mock_http):
            resp = await client.post(
                "/api/indexers/caps",
                json={"host": "https://indexer.example.com", "api_key": "wrongkey"},
                headers=admin_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is False
        assert "HTTP 403" in data["error"]

    async def test_caps_generic_exception(self, client: AsyncClient, admin_headers):
        """Returns connected=False for any other unexpected exception."""
        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)
        mock_http.get = AsyncMock(side_effect=ConnectionError("refused"))
        with patch("httpx.AsyncClient", return_value=mock_http):
            resp = await client.post(
                "/api/indexers/caps",
                json={"host": "https://indexer.example.com", "api_key": "abc"},
                headers=admin_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is False
        assert data["error"] == "refused"

    async def test_caps_categories_top_level_dict(
        self, client: AsyncClient, admin_headers
    ):
        """Handles categories as a top-level dict key (non-channel response format)."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        # No "channel" key → falls back to top-level "categories"
        # "category" is a single dict (not a list) to cover the second isinstance check
        mock_resp.json.return_value = {
            "categories": {
                "category": {
                    "@attributes": {"id": "5000", "name": "TV"},
                }
            }
        }
        mock_http = self._make_mock_http_client(mock_resp)
        with patch("httpx.AsyncClient", return_value=mock_http):
            resp = await client.post(
                "/api/indexers/caps",
                json={"host": "https://indexer.example.com", "api_key": "abc"},
                headers=admin_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is True
        assert len(data["categories"]) == 1
        assert data["categories"][0]["name"] == "TV"

    async def test_caps_invalid_category_id_skipped(
        self, client: AsyncClient, admin_headers
    ):
        """Categories with non-numeric IDs are skipped via the ValueError/TypeError handler."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "channel": {
                "categories": {
                    "category": [
                        {"@attributes": {"id": "not_a_number", "name": "Bad"}},
                        {"@attributes": {"id": "2000", "name": "Movies"}},
                    ]
                }
            }
        }
        mock_http = self._make_mock_http_client(mock_resp)
        with patch("httpx.AsyncClient", return_value=mock_http):
            resp = await client.post(
                "/api/indexers/caps",
                json={"host": "https://indexer.example.com", "api_key": "abc"},
                headers=admin_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is True
        # Only the valid category should be in the result
        assert len(data["categories"]) == 1
        assert data["categories"][0]["name"] == "Movies"

    async def test_caps_subcat_as_single_dict(
        self, client: AsyncClient, admin_headers
    ):
        """A single subcat dict (not list) is wrapped into a list correctly."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "channel": {
                "categories": {
                    "category": [
                        {
                            "@attributes": {"id": "2000", "name": "Movies"},
                            "subcat": {"@attributes": {"id": "2010", "name": "Movies/HD"}},
                        }
                    ]
                }
            }
        }
        mock_http = self._make_mock_http_client(mock_resp)
        with patch("httpx.AsyncClient", return_value=mock_http):
            resp = await client.post(
                "/api/indexers/caps",
                json={"host": "https://indexer.example.com", "api_key": "abc"},
                headers=admin_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is True
        assert data["categories"][0]["subcategories"][0]["name"] == "Movies/HD"

    async def test_caps_invalid_subcat_id_skipped(
        self, client: AsyncClient, admin_headers
    ):
        """Subcategories with non-numeric IDs are skipped via the inner ValueError handler."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "channel": {
                "categories": {
                    "category": [
                        {
                            "@attributes": {"id": "2000", "name": "Movies"},
                            "subcat": [
                                {"@attributes": {"id": "not_a_number", "name": "Bad Sub"}},
                                {"@attributes": {"id": "2010", "name": "Movies/HD"}},
                            ],
                        }
                    ]
                }
            }
        }
        mock_http = self._make_mock_http_client(mock_resp)
        with patch("httpx.AsyncClient", return_value=mock_http):
            resp = await client.post(
                "/api/indexers/caps",
                json={"host": "https://indexer.example.com", "api_key": "abc"},
                headers=admin_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is True
        # Only the valid subcat
        assert len(data["categories"][0]["subcategories"]) == 1
        assert data["categories"][0]["subcategories"][0]["name"] == "Movies/HD"

    async def test_caps_categories_not_list_returns_empty(
        self, client: AsyncClient, admin_headers
    ):
        """When categories_raw is not a dict/list, parse_categories returns empty list."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        # "categories" value is a plain string (not dict or list)
        mock_resp.json.return_value = {
            "channel": {"categories": "invalid_data"}
        }
        mock_http = self._make_mock_http_client(mock_resp)
        with patch("httpx.AsyncClient", return_value=mock_http):
            resp = await client.post(
                "/api/indexers/caps",
                json={"host": "https://indexer.example.com", "api_key": "abc"},
                headers=admin_headers,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["connected"] is True
        assert data["categories"] == []

    async def test_caps_unauthenticated(self, client: AsyncClient):
        resp = await client.post(
            "/api/indexers/caps",
            json={"host": "https://indexer.example.com", "api_key": "abc"},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/indexers
# ---------------------------------------------------------------------------
class TestListIndexers:
    async def test_list_indexers_empty(self, client: AsyncClient, admin_headers):
        resp = await client.get("/api/indexers", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_indexers(self, client: AsyncClient, db_session, admin_headers):
        await _create_indexer(db_session, label="Indexer A")
        await _create_indexer(db_session, label="Indexer B")
        resp = await client.get("/api/indexers", headers=admin_headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    async def test_list_indexers_unauthenticated(self, client: AsyncClient):
        resp = await client.get("/api/indexers")
        assert resp.status_code == 401

    async def test_list_indexers_forbidden_for_regular_user(
        self, client: AsyncClient, user_headers
    ):
        resp = await client.get("/api/indexers", headers=user_headers)
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /api/indexers
# ---------------------------------------------------------------------------
class TestCreateIndexer:
    async def test_create_indexer(self, client: AsyncClient, admin_headers):
        resp = await client.post(
            "/api/indexers",
            json={
                "label": "NZBgeek",
                "host": "https://api.nzbgeek.info",
                "api_key": "secret",
                "ssl": True,
                "verify_ssl": True,
                "type": "newznab",
            },
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["label"] == "NZBgeek"
        assert data["guid"] is not None

    async def test_create_indexer_with_categories(
        self, client: AsyncClient, admin_headers
    ):
        resp = await client.post(
            "/api/indexers",
            json={
                "label": "NZBwith cats",
                "host": "https://api.nzbgeek.info",
                "api_key": "secret",
                "ssl": False,
                "verify_ssl": True,
                "type": "newznab",
                "categories": [
                    {"label": "Movies", "category_type": "movie", "newznab_category_id": 2000}
                ],
            },
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["categories"]) == 1
        assert data["categories"][0]["label"] == "Movies"

    async def test_create_indexer_unauthenticated(self, client: AsyncClient):
        resp = await client.post(
            "/api/indexers",
            json={
                "label": "X",
                "host": "https://x.com",
                "api_key": "k",
                "ssl": False,
                "verify_ssl": True,
                "type": "newznab",
            },
        )
        assert resp.status_code == 401

    async def test_create_indexer_forbidden_for_regular_user(
        self, client: AsyncClient, user_headers
    ):
        resp = await client.post(
            "/api/indexers",
            json={
                "label": "X",
                "host": "https://x.com",
                "api_key": "k",
                "ssl": False,
                "verify_ssl": True,
                "type": "newznab",
            },
            headers=user_headers,
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/indexers/{id}
# ---------------------------------------------------------------------------
class TestGetIndexer:
    async def test_get_indexer(self, client: AsyncClient, admin_headers):
        # Create via the API to ensure the indexer is in the same DB session context
        create_resp = await client.post(
            "/api/indexers",
            json={
                "label": "Test Indexer",
                "host": "https://indexer.example.com",
                "api_key": "test-api-key",
                "ssl": True,
                "verify_ssl": True,
                "type": "newznab",
            },
            headers=admin_headers,
        )
        assert create_resp.status_code == 200
        indexer_id = create_resp.json()["guid"]

        resp = await client.get(f"/api/indexers/{indexer_id}", headers=admin_headers)
        assert resp.status_code == 200, f"Got {resp.status_code}: {resp.text}"
        assert resp.json()["guid"] == indexer_id
        assert resp.json()["label"] == "Test Indexer"


# ---------------------------------------------------------------------------
# PUT /api/indexers/{id}
# ---------------------------------------------------------------------------
class TestUpdateIndexer:
    async def test_update_indexer(
        self, client: AsyncClient, db_session, admin_headers
    ):
        indexer = await _create_indexer(db_session)
        resp = await client.put(
            f"/api/indexers/{indexer.guid}",
            json={
                "label": "Updated Label",
                "host": "https://new.host.com",
                "api_key": "newkey",
                "ssl": False,
                "verify_ssl": True,
                "type": "torznab",
            },
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["label"] == "Updated Label"
        assert resp.json()["type"] == "torznab"

    async def test_update_indexer_not_found(
        self, client: AsyncClient, admin_headers
    ):
        resp = await client.put(
            f"/api/indexers/{uuid.uuid4()}",
            json={
                "label": "X",
                "host": "https://x.com",
                "api_key": "k",
                "ssl": False,
                "verify_ssl": True,
                "type": "newznab",
            },
            headers=admin_headers,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/indexers/{id}
# ---------------------------------------------------------------------------
class TestDeleteIndexer:
    async def test_delete_indexer(
        self, client: AsyncClient, db_session, admin_headers
    ):
        indexer = await _create_indexer(db_session)
        resp = await client.delete(f"/api/indexers/{indexer.guid}", headers=admin_headers)
        assert resp.status_code == 204

    async def test_delete_indexer_not_found(
        self, client: AsyncClient, admin_headers
    ):
        resp = await client.delete(
            f"/api/indexers/{uuid.uuid4()}", headers=admin_headers
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/indexers/{id}/categories
# ---------------------------------------------------------------------------
class TestListIndexerCategories:
    async def test_list_categories_empty(
        self, client: AsyncClient, db_session, admin_headers
    ):
        indexer = await _create_indexer(db_session)
        resp = await client.get(
            f"/api/indexers/{indexer.guid}/categories", headers=admin_headers
        )
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_categories_not_found(
        self, client: AsyncClient, admin_headers
    ):
        resp = await client.get(
            f"/api/indexers/{uuid.uuid4()}/categories", headers=admin_headers
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PUT /api/indexers/{id}/categories
# ---------------------------------------------------------------------------
class TestSetIndexerCategories:
    async def test_set_categories(
        self, client: AsyncClient, db_session, admin_headers
    ):
        indexer = await _create_indexer(db_session)
        categories_payload = [
            {"label": "Movies", "category_type": "movie", "newznab_category_id": 2000},
            {"label": "TV", "category_type": "show", "newznab_category_id": 5000},
        ]
        resp = await client.put(
            f"/api/indexers/{indexer.guid}/categories",
            json=categories_payload,
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        labels = {c["label"] for c in data}
        assert labels == {"Movies", "TV"}

    async def test_set_categories_not_found(
        self, client: AsyncClient, admin_headers
    ):
        resp = await client.put(
            f"/api/indexers/{uuid.uuid4()}/categories",
            json=[],
            headers=admin_headers,
        )
        assert resp.status_code == 404
