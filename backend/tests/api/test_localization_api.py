"""Tests for public localization endpoints (/api/localization/*)."""

from httpx import AsyncClient


class TestLocalizationApi:
    async def test_public_can_read_localization_options(self, client: AsyncClient):
        resp = await client.get("/api/localization/options")

        assert resp.status_code == 200
        data = resp.json()
        assert data["default_locale"] == "de-DE"
        assert data["supported_locales"] == ["en-US", "de-DE"]
        assert [culture["name"] for culture in data["cultures"]] == [
            "en-US",
            "de-DE",
        ]
        assert [country["two_letter_iso_region_name"] for country in data["countries"]] == [
            "US",
            "DE",
        ]

    async def test_public_can_read_cultures(self, client: AsyncClient):
        resp = await client.get("/api/localization/cultures")

        assert resp.status_code == 200
        cultures = resp.json()
        assert cultures[0]["name"] == "en-US"
        assert cultures[1]["native_name"] == "Deutsch (Deutschland)"

    async def test_public_can_read_countries(self, client: AsyncClient):
        resp = await client.get("/api/localization/countries")

        assert resp.status_code == 200
        countries = resp.json()
        assert countries[0]["three_letter_iso_region_name"] == "USA"
        assert countries[1]["display_name"] == "Germany"

    async def test_public_can_read_parental_ratings(self, client: AsyncClient):
        resp = await client.get("/api/localization/parental-ratings")

        assert resp.status_code == 200
        ratings = resp.json()
        assert {"name": "PG-13", "value": 13, "country": "US"} in ratings
        assert {"name": "FSK 16", "value": 16, "country": "DE"} in ratings
