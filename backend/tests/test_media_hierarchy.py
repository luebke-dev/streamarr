"""Unit tests for the shared show/season/episode rules.

``services.media_hierarchy`` is the single place that knows both shapes of the
show tree: the plugin's ``SHOWS -> SEASONS -> EPISODES`` typing and the
``SHOWS``-all-the-way-down rows older importers wrote. Everything that
branches on "is this an episode?" goes through it, so the shapes are pinned
here rather than through the endpoints that consume them.
"""

import uuid
from types import SimpleNamespace

from streamarr.models.media import MediaType
from streamarr.services.media_hierarchy import (
    EPISODE,
    SEASON,
    SHOW,
    episode_type,
    hierarchy_labels,
    is_show_tree,
    show_level,
    show_tree_types,
)


def _item(media_type, *, parent=None, sequence=None, title=None):
    return SimpleNamespace(
        guid=uuid.uuid4(),
        media_type=media_type,
        parent_guid=parent.guid if parent is not None else None,
        sequence_number=sequence,
        title=title if title is not None else f"item-{sequence}",
    )


class TestShowTreeTypes:
    def test_contains_all_three_levels(self):
        assert show_tree_types() == {
            MediaType.SHOWS,
            MediaType.SEASONS,
            MediaType.EPISODES,
        }

    def test_matches_show_tree_members_only(self):
        assert is_show_tree(MediaType.SHOWS)
        assert is_show_tree(MediaType.SEASONS)
        assert is_show_tree(MediaType.EPISODES)
        assert not is_show_tree(MediaType.MOVIES)
        # MediaType is a str enum, so the raw value matches too - several call
        # sites compare a media_type column against "SHOWS".
        assert is_show_tree("SHOWS")

    def test_episode_type_is_the_typed_episode(self):
        assert episode_type() == MediaType.EPISODES


class TestShowLevel:
    def test_root_item_is_a_show(self):
        show = _item(MediaType.SHOWS, title="Boardwalk Empire")
        assert show_level(show, None) == SHOW

    def test_typed_episode_under_a_season(self):
        show = _item(MediaType.SHOWS)
        season = _item(MediaType.SEASONS, parent=show, sequence=3)
        episode = _item(MediaType.EPISODES, parent=season, sequence=8)
        assert show_level(episode, season) == EPISODE

    def test_typed_episode_hanging_directly_off_a_show(self):
        """Some importers skip the season row; the type still says episode."""
        show = _item(MediaType.SHOWS)
        episode = _item(MediaType.EPISODES, parent=show, sequence=8)
        assert show_level(episode, show) == EPISODE

    def test_typed_season(self):
        show = _item(MediaType.SHOWS)
        season = _item(MediaType.SEASONS, parent=show, sequence=3)
        assert show_level(season, show) == SEASON

    def test_legacy_shows_typed_season_and_episode(self):
        show = _item(MediaType.SHOWS)
        season = _item(MediaType.SHOWS, parent=show, sequence=3)
        episode = _item(MediaType.SHOWS, parent=season, sequence=8)
        assert show_level(season, show) == SEASON
        assert show_level(episode, season) == EPISODE


class TestHierarchyLabels:
    def test_episode_reports_numbers_and_the_show(self):
        show = _item(MediaType.SHOWS, title="Boardwalk Empire")
        season = _item(MediaType.SEASONS, parent=show, sequence=3)
        episode = _item(MediaType.EPISODES, parent=season, sequence=8, title="Das Pony")

        labels = hierarchy_labels(episode, season, show)

        assert labels == {
            "show_title": "Boardwalk Empire",
            "show_guid": show.guid,
            "season_number": 3,
            "episode_number": 8,
        }

    def test_episode_of_an_orphaned_season_keeps_the_numbers_only(self):
        """A season row is not a show: its title must not become show_title."""
        season = _item(MediaType.SEASONS, sequence=3, title="Season 3")
        episode = _item(MediaType.EPISODES, parent=season, sequence=8)

        labels = hierarchy_labels(episode, season, None)

        assert labels["season_number"] == 3
        assert labels["episode_number"] == 8
        assert labels["show_title"] is None
        assert labels["show_guid"] is None

    def test_episode_hanging_directly_off_a_show_uses_it(self):
        show = _item(MediaType.SHOWS, title="Boardwalk Empire")
        episode = _item(MediaType.EPISODES, parent=show, sequence=8)

        labels = hierarchy_labels(episode, show, None)

        assert labels["show_title"] == "Boardwalk Empire"
        assert labels["show_guid"] == show.guid
        assert labels["episode_number"] == 8
        assert labels["season_number"] is None

    def test_season_reports_its_own_number_and_no_episode(self):
        show = _item(MediaType.SHOWS, title="Boardwalk Empire")
        season = _item(MediaType.SEASONS, parent=show, sequence=3)

        labels = hierarchy_labels(season, show, None)

        assert labels["show_title"] == "Boardwalk Empire"
        assert labels["show_guid"] == show.guid
        assert labels["season_number"] == 3
        assert labels["episode_number"] is None

    def test_show_reports_nothing(self):
        show = _item(MediaType.SHOWS, title="Boardwalk Empire")

        assert hierarchy_labels(show, None, None) == {
            "show_title": None,
            "show_guid": None,
            "season_number": None,
            "episode_number": None,
        }

    def test_legacy_chain_resolves_like_the_typed_one(self):
        show = _item(MediaType.SHOWS, title="Boardwalk Empire")
        season = _item(MediaType.SHOWS, parent=show, sequence=3)
        episode = _item(MediaType.SHOWS, parent=season, sequence=8)

        typed = hierarchy_labels(
            _item(MediaType.EPISODES, parent=season, sequence=8), season, show
        )
        legacy = hierarchy_labels(episode, season, show)

        assert legacy["season_number"] == typed["season_number"] == 3
        assert legacy["episode_number"] == typed["episode_number"] == 8
        assert legacy["show_title"] == typed["show_title"] == "Boardwalk Empire"
