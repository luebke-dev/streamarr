"""Tests for pyrate.api.utils module."""

import pytest
from unittest.mock import MagicMock

from pyrate.api.utils import get_user_locale


class TestGetUserLocale:
    def test_no_accept_language_header(self):
        mock_request = MagicMock()
        mock_request.headers = {}
        assert get_user_locale(mock_request) == "en-US"

    def test_empty_accept_language(self):
        mock_request = MagicMock()
        mock_request.headers = {"accept-language": ""}
        assert get_user_locale(mock_request) == "en-US"

    def test_german_short(self):
        mock_request = MagicMock()
        mock_request.headers = {"accept-language": "de"}
        assert get_user_locale(mock_request) == "de-DE"

    def test_german_full(self):
        mock_request = MagicMock()
        mock_request.headers = {"accept-language": "de-DE,de;q=0.9"}
        assert get_user_locale(mock_request) == "de-DE"

    def test_german_at(self):
        mock_request = MagicMock()
        mock_request.headers = {"accept-language": "de-AT"}
        assert get_user_locale(mock_request) == "de-DE"

    def test_english_short(self):
        mock_request = MagicMock()
        mock_request.headers = {"accept-language": "en"}
        assert get_user_locale(mock_request) == "en-US"

    def test_english_gb(self):
        mock_request = MagicMock()
        mock_request.headers = {"accept-language": "en-GB,en;q=0.9"}
        assert get_user_locale(mock_request) == "en-US"

    def test_french_with_hyphen(self):
        mock_request = MagicMock()
        mock_request.headers = {"accept-language": "fr-FR"}
        assert get_user_locale(mock_request) == "fr-FR"

    def test_japanese_with_hyphen(self):
        mock_request = MagicMock()
        mock_request.headers = {"accept-language": "ja-JP"}
        assert get_user_locale(mock_request) == "ja-JP"

    def test_french_no_hyphen(self):
        """French without region code has no hyphen, so falls through to default."""
        mock_request = MagicMock()
        mock_request.headers = {"accept-language": "fr"}
        assert get_user_locale(mock_request) == "en-US"

    def test_quality_values_parsed_correctly(self):
        mock_request = MagicMock()
        mock_request.headers = {
            "accept-language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7"
        }
        assert get_user_locale(mock_request) == "de-DE"

    def test_english_us_direct(self):
        mock_request = MagicMock()
        mock_request.headers = {"accept-language": "en-US"}
        assert get_user_locale(mock_request) == "en-US"
