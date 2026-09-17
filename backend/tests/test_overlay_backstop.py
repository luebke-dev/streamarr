"""The backstop must not re-queue work it has established is pointless.

An OverlayApplication row only appears once a template has really been
rendered onto an item, so "no row yet" is the backstop's only notion of
outstanding work. That makes it blind in one direction: an item no template
can apply to never gets a row, so it stays outstanding forever and the tick
re-queues it every half hour for good.
"""

import pytest

from streamarr.models.media import MediaItem, MediaType
from streamarr.models.overlay import OverlayMediaScope, OverlayTarget, OverlayTemplate
from streamarr.workers.overlay_worker import (
    _scoped_media_types,
    tick_render_missing_overlays_impl,
)


def _template(name, *, enabled=True, scope=OverlayMediaScope.BOTH,
              target=OverlayTarget.POSTER):
    return OverlayTemplate(
        name=name, enabled=enabled, media_scope=scope, target=target, elements=[]
    )


def _item(title, media_type=MediaType.MOVIES, poster="/p.jpg"):
    return MediaItem(media_type=media_type, title=title, poster_path=poster)


class TestScopedMediaTypes:
    @pytest.mark.asyncio
    async def test_no_enabled_template_means_no_media_types(self, db_session):
        db_session.add(_template("4K badge", enabled=False))
        await db_session.flush()
        assert await _scoped_media_types(db_session, OverlayTarget.POSTER) == ()

    @pytest.mark.asyncio
    async def test_only_the_scopes_of_enabled_templates_count(self, db_session):
        db_session.add_all([
            _template("movies only", scope=OverlayMediaScope.MOVIE),
            _template("shows too", scope=OverlayMediaScope.SHOW, enabled=False),
        ])
        await db_session.flush()
        assert await _scoped_media_types(db_session, OverlayTarget.POSTER) == ("MOVIES",)

    @pytest.mark.asyncio
    async def test_scopes_from_several_templates_are_merged(self, db_session):
        db_session.add_all([
            _template("a", scope=OverlayMediaScope.MOVIE),
            _template("b", scope=OverlayMediaScope.SHOW),
        ])
        await db_session.flush()
        assert set(await _scoped_media_types(db_session, OverlayTarget.POSTER)) == {
            "MOVIES", "SHOWS",
        }

    @pytest.mark.asyncio
    async def test_a_template_for_another_target_does_not_count(self, db_session):
        db_session.add(_template("backdrop", target=OverlayTarget.BACKDROP))
        await db_session.flush()
        assert await _scoped_media_types(db_session, OverlayTarget.POSTER) == ()


class TestBackstopTick:
    @pytest.mark.asyncio
    async def test_all_templates_disabled_queues_nothing(self, db_session, monkeypatch):
        import streamarr.workers.overlay_worker as mod

        db_session.add_all([
            _template("4K badge", enabled=False),
            _item("Parasite"),
        ])
        await db_session.commit()

        monkeypatch.setattr(mod, "_overlays_enabled", _true)
        monkeypatch.setattr(mod, "sessionmanager", _Sessions(db_session))

        # overlays.enabled defaults to true, so the switch alone said nothing
        # about whether there was an overlay to draw — and every render came
        # straight back with "no-applicable-templates".
        assert await tick_render_missing_overlays_impl() == 0

    @pytest.mark.asyncio
    async def test_items_outside_every_enabled_scope_are_left_alone(
        self, db_session, monkeypatch
    ):
        import streamarr.workers.overlay_worker as mod

        db_session.add_all([
            _template("movies only", scope=OverlayMediaScope.MOVIE),
            _item("Nur eine Serie", media_type=MediaType.SHOWS),
        ])
        await db_session.commit()

        queued = []
        monkeypatch.setattr(mod, "_overlays_enabled", _true)
        monkeypatch.setattr(mod, "sessionmanager", _Sessions(db_session))

        # No movie to render, and the show can never match, so nothing is due.
        assert await tick_render_missing_overlays_impl() == 0
        assert queued == []


async def _true() -> bool:
    return True


class _Sessions:
    """Hand the worker the test's own session instead of a fresh one."""

    def __init__(self, session):
        self._session = session

    def session(self):
        import contextlib

        @contextlib.asynccontextmanager
        async def _cm():
            yield self._session

        return _cm()
