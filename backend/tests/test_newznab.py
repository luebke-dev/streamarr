"""Tests for Newznab plugin - size extraction from API responses."""

from pyrate.indexers.newznab import Newznab


class TestExtractSize:
    """Tests for Newznab._extract_size() method."""

    def test_size_from_enclosure_attributes(self):
        """Size should be extracted from enclosure.@attributes.length."""
        item = {
            "title": "Some.Release.1080p",
            "enclosure": {
                "@attributes": {
                    "url": "https://example.com/nzb/123",
                    "length": "1500000000",
                    "type": "application/x-nzb",
                }
            },
        }
        assert Newznab._extract_size(item) == 1500000000

    def test_size_from_newznab_attr(self):
        """Size should be extracted from newznab:attr with name=size."""
        item = {
            "title": "Some.Release.1080p",
            "newznab:attr": [
                {"@attributes": {"name": "category", "value": "2000"}},
                {"@attributes": {"name": "size", "value": "2500000000"}},
            ],
        }
        assert Newznab._extract_size(item) == 2500000000

    def test_size_from_attr_key(self):
        """Size should also work with 'attr' key (alternative format)."""
        item = {
            "title": "Some.Release.1080p",
            "attr": [
                {"@attributes": {"name": "size", "value": "3000000000"}},
            ],
        }
        assert Newznab._extract_size(item) == 3000000000

    def test_enclosure_takes_priority(self):
        """Enclosure size should be returned first if both exist."""
        item = {
            "title": "Some.Release.1080p",
            "enclosure": {
                "@attributes": {
                    "length": "1000000000",
                }
            },
            "newznab:attr": [
                {"@attributes": {"name": "size", "value": "2000000000"}},
            ],
        }
        assert Newznab._extract_size(item) == 1000000000

    def test_no_size_info(self):
        """Returns None when no size information is available."""
        item = {"title": "Some.Release.1080p"}
        assert Newznab._extract_size(item) is None

    def test_empty_enclosure(self):
        """Returns None for empty enclosure."""
        item = {"title": "Some.Release", "enclosure": {}}
        assert Newznab._extract_size(item) is None

    def test_zero_length_enclosure(self):
        """Returns None for zero-length enclosure."""
        item = {
            "enclosure": {"@attributes": {"length": "0"}},
        }
        assert Newznab._extract_size(item) is None

    def test_invalid_length_string(self):
        """Returns None for non-numeric enclosure length."""
        item = {
            "enclosure": {"@attributes": {"length": "invalid"}},
        }
        assert Newznab._extract_size(item) is None

    def test_single_attr_dict(self):
        """Handle newznab:attr as a single dict instead of list."""
        item = {
            "newznab:attr": {"@attributes": {"name": "size", "value": "500000000"}},
        }
        assert Newznab._extract_size(item) == 500000000

    def test_attr_without_size(self):
        """Returns None when attrs exist but no size attribute."""
        item = {
            "newznab:attr": [
                {"@attributes": {"name": "category", "value": "2000"}},
                {"@attributes": {"name": "grabs", "value": "15"}},
            ],
        }
        assert Newznab._extract_size(item) is None

    def test_fallback_from_empty_enclosure_to_attr(self):
        """Falls back to attr when enclosure has no length."""
        item = {
            "enclosure": {"@attributes": {"url": "https://example.com/nzb"}},
            "newznab:attr": [
                {"@attributes": {"name": "size", "value": "750000000"}},
            ],
        }
        assert Newznab._extract_size(item) == 750000000
