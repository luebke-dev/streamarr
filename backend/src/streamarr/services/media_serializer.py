"""Serialization helpers for media API responses."""

from __future__ import annotations

from urllib.parse import quote

from streamarr.models.media import MediaItem, MediaType
from streamarr.utils.extra_data import load_extra_data
from streamarr.schemas.media import MediaExternalLinkRead


def load_media_extra_data(media_item: MediaItem) -> dict:
    return load_extra_data(media_item)


def _provider_key(provider: str) -> str:
    return provider.strip().lower().replace("-", "_")


def _provider_display_name(provider: str) -> str:
    return {
        "tmdb": "TMDB",
        "tmdb_movie": "TMDB",
        "tmdb_tv": "TMDB",
        "imdb": "IMDb",
        "imdb_id": "IMDb",
        "tvdb": "TheTVDB",
        "tvdb_id": "TheTVDB",
        "igdb": "IGDB",
        "spotify": "Spotify",
        "musicbrainz": "MusicBrainz",
        "musicbrainz_artist": "MusicBrainz",
        "musicbrainz_album": "MusicBrainz",
        "musicbrainz_recording": "MusicBrainz",
        "openlibrary": "Open Library",
        "openlibrary_id": "Open Library",
        "isbn": "ISBN",
        "isrc": "ISRC",
    }.get(_provider_key(provider), provider.strip() or "External")


def _external_url(provider: str, provider_id: str, media_type: MediaType) -> str | None:
    provider_key = _provider_key(provider)
    encoded_id = quote(str(provider_id).strip(), safe="")
    if not encoded_id:
        return None

    if provider_key in {"imdb", "imdb_id"}:
        return f"https://www.imdb.com/title/{encoded_id}/"
    if provider_key in {"tvdb", "tvdb_id"}:
        return f"https://thetvdb.com/dereferrer/series/{encoded_id}"
    if provider_key in {"tmdb", "tmdb_id"}:
        tmdb_kind = "tv" if media_type == MediaType.SHOWS else "movie"
        return f"https://www.themoviedb.org/{tmdb_kind}/{encoded_id}"
    if provider_key == "tmdb_movie":
        return f"https://www.themoviedb.org/movie/{encoded_id}"
    if provider_key == "tmdb_tv":
        return f"https://www.themoviedb.org/tv/{encoded_id}"
    if provider_key == "igdb":
        return f"https://www.igdb.com/games/{encoded_id}"
    if provider_key == "spotify":
        spotify_kind = "track"
        if media_type == MediaType.ARTISTS:
            spotify_kind = "artist"
        elif media_type == MediaType.ALBUMS:
            spotify_kind = "album"
        return f"https://open.spotify.com/{spotify_kind}/{encoded_id}"
    if provider_key in {"musicbrainz", "musicbrainz_recording"}:
        return f"https://musicbrainz.org/recording/{encoded_id}"
    if provider_key == "musicbrainz_artist":
        return f"https://musicbrainz.org/artist/{encoded_id}"
    if provider_key == "musicbrainz_album":
        return f"https://musicbrainz.org/release-group/{encoded_id}"
    if provider_key in {"openlibrary", "openlibrary_id"}:
        if str(provider_id).startswith("/"):
            return f"https://openlibrary.org{provider_id}"
        return f"https://openlibrary.org/works/{encoded_id}"
    if provider_key == "isbn":
        return f"https://openlibrary.org/isbn/{encoded_id}"
    if provider_key == "isrc":
        return f"https://isrcsearch.ifpi.org/#!/search?isrcCode={encoded_id}"
    return None


def _external_id_entries(media_item: MediaItem) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = [
        (external_id.provider, external_id.external_id)
        for external_id in media_item.external_ids
    ]

    raw_external_ids = load_media_extra_data(media_item).get("external_ids")
    if isinstance(raw_external_ids, dict):
        for provider, provider_id in raw_external_ids.items():
            if provider_id is not None:
                entries.append((str(provider), str(provider_id)))

    seen = set()
    unique_entries = []
    for provider, provider_id in entries:
        key = (_provider_key(provider), str(provider_id).strip())
        if not key[0] or not key[1] or key in seen:
            continue
        seen.add(key)
        unique_entries.append((provider, key[1]))
    return unique_entries


def external_links_for_media(media_item: MediaItem) -> list[MediaExternalLinkRead]:
    links = []
    for provider, provider_id in _external_id_entries(media_item):
        url = _external_url(provider, provider_id, media_item.media_type)
        if not url:
            continue
        links.append(
            MediaExternalLinkRead(
                provider=_provider_key(provider),
                provider_id=provider_id,
                display_name=_provider_display_name(provider),
                url=url,
            )
        )
    return links


def _media_file_payload(file) -> dict:
    return {
        "guid": file.guid,
        "media_item_guid": file.media_item_guid,
        "file_path": file.file_path,
        "file_name": file.file_name,
        "file_size": file.file_size,
        "duration": file.duration,
        "width": file.width,
        "height": file.height,
        "codec": file.codec,
        "bitrate": file.bitrate,
        "quality": file.quality,
        "format": file.format,
        "probe_data": file.probe_data,
        "created_at": file.created_at,
        "updated_at": file.updated_at,
        "imported_at": file.imported_at,
    }


def _release_payload(release) -> dict:
    return {
        "guid": release.guid,
        "media_item_guid": release.media_item_guid,
        "indexer_guid": release.indexer_guid,
        "title": release.title,
        "size": release.size,
        "quality": release.quality,
        "score": release.score,
        "release_metadata": release.release_metadata,
        "publish_date": release.publish_date,
        "created_at": release.created_at,
        "links": [
            {
                "guid": link.guid,
                "link": link.link,
                "link_type": link.link_type,
                "created_at": link.created_at,
            }
            for link in release.links
        ],
    }


def _external_id_payload(external_id) -> dict:
    return {
        "guid": external_id.guid,
        "provider": external_id.provider,
        "external_id": external_id.external_id,
        "created_at": external_id.created_at,
    }


def _cast_payload(cast_entry) -> dict:
    return {
        "guid": cast_entry.guid,
        "media_item_guid": cast_entry.media_item_guid,
        "person_guid": cast_entry.person_guid,
        "character": cast_entry.character,
        "department": cast_entry.department,
        "job": cast_entry.job,
        "cast_order": cast_entry.cast_order,
        "created_at": cast_entry.created_at,
        "person": {
            "guid": cast_entry.person.guid,
            "name": cast_entry.person.name,
            "tmdb_id": cast_entry.person.tmdb_id,
            "profile_path": cast_entry.person.profile_path,
            "known_for_department": cast_entry.person.known_for_department,
            "created_at": cast_entry.person.created_at,
            "updated_at": cast_entry.person.updated_at,
        },
    }


def minimal_media_item_detail(media_item: MediaItem) -> dict:
    return media_item_detail_payload(
        media_item,
        load_files=False,
        load_releases=False,
        load_external_ids=True,
    )


def media_item_detail_payload(
    media_item: MediaItem,
    *,
    load_files: bool,
    load_releases: bool,
    load_external_ids: bool,
    show_title: str | None = None,
    show_guid=None,
    season_number: int | None = None,
    episode_number: int | None = None,
    cast_entries=None,
) -> dict:
    """Build the dict consumed by ``MediaItemDetail``."""
    return {
        "guid": media_item.guid,
        "media_type": media_item.media_type,
        "parent_guid": media_item.parent_guid,
        "title": media_item.title,
        "original_title": media_item.original_title,
        "description": media_item.description,
        "tagline": media_item.tagline,
        "release_date": media_item.release_date,
        "poster_path": media_item.poster_path,
        "backdrop_path": media_item.backdrop_path,
        "content_rating": media_item.content_rating,
        "min_age": media_item.min_age,
        "extra_data": media_item.extra_data,
        "sequence_number": media_item.sequence_number,
        "availability_status": media_item.availability_status,
        "created_at": media_item.created_at,
        "updated_at": media_item.updated_at,
        "last_searched_at": media_item.last_searched_at,
        "last_metadata_updated_at": media_item.last_metadata_updated_at,
        "show_title": show_title,
        "show_guid": show_guid,
        "season_number": season_number,
        "episode_number": episode_number,
        "files": [
            _media_file_payload(file)
            for file in (media_item.files if load_files else [])
        ],
        "releases": [
            _release_payload(release)
            for release in (media_item.releases if load_releases else [])
        ],
        "external_ids": [
            _external_id_payload(external_id)
            for external_id in (
                media_item.external_ids if load_external_ids else []
            )
        ],
        "external_links": (
            external_links_for_media(media_item) if load_external_ids else []
        ),
        "cast": [_cast_payload(entry) for entry in (cast_entries or [])],
    }
