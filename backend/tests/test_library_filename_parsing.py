import pytest

from streamarr.libraries.movies import MovieLibraryPlugin
from streamarr.libraries.shows import ShowLibraryPlugin


@pytest.mark.asyncio
async def test_movie_parser_groups_versions_parts_and_provider_ids():
    parsed = await MovieLibraryPlugin().extract_metadata_from_filename(
        "Arrival (2016) [tmdbid-329865] - 2160p.mkv"
    )
    multipart = await MovieLibraryPlugin().extract_metadata_from_filename(
        "Arrival (2016) cd2.mkv"
    )

    assert parsed["title"] == "Arrival"
    assert parsed["year"] == 2016
    assert parsed["external_ids"] == {"tmdb": "329865"}
    assert parsed["version_label"] == "2160p"
    assert multipart["title"] == "Arrival"
    assert multipart["part_number"] == "2"


@pytest.mark.asyncio
async def test_show_parser_understands_episode_ranges():
    parsed = await ShowLibraryPlugin().extract_metadata_from_filename(
        "Show.Name.S01E01-E03.1080p.mkv"
    )

    assert parsed["season"] == 1
    assert parsed["episode"] == 1
    assert parsed["episode_end"] == 3
