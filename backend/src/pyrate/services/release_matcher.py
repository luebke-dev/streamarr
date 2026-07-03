"""
Release matching service for Sonarr/Radarr-style title matching.

This service provides intelligent matching of release titles against media items,
similar to how Sonarr and Radarr match releases.
"""

import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from pyrate.parsers.release_parser import ReleaseParser

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    """Result of a release match attempt."""

    is_match: bool
    score: float  # 0.0 to 1.0, higher is better match
    match_type: str  # "exact", "normalized", "fuzzy", "year", "id", "no_match"
    details: dict[str, Any]


class ReleaseMatcher:
    """
    Matches release titles against media items using multiple strategies.

    Match priority (highest to lowest):
    1. External ID match (IMDB, TVDB, TMDB) - score 1.0
    2. Exact title match - score 0.95
    3. Normalized title match - score 0.90
    4. Title + year match - score 0.85
    5. Fuzzy title match (>= 85% similarity) - score based on similarity
    6. No match - score 0.0
    """

    # Minimum similarity threshold for fuzzy matching
    FUZZY_THRESHOLD = 0.80

    # Score bonuses
    YEAR_MATCH_BONUS = 0.05
    SEASON_EPISODE_MATCH_BONUS = 0.10

    # Rejection patterns (Sonarr-inspired)
    _RAW_DISK_RE = re.compile(
        r"\b(DISC|BDMV|VIDEO_TS|ISO|VOB|COMPLETE\.BLURAY)\b", re.IGNORECASE
    )
    _MULTI_SEASON_RE = re.compile(
        r"\bS\d{1,2}\s*[-–]\s*S\d{1,2}\b", re.IGNORECASE
    )

    # Minimum size for video releases (50 MB) — smaller is likely a sample
    MIN_VIDEO_SIZE_BYTES = 50 * 1024 * 1024

    @classmethod
    def should_reject_release(
        cls,
        release: dict[str, Any],
        is_single_episode: bool = False,
        media_release_date: str | None = None,
        is_book: bool = False,
    ) -> str | None:
        """
        Check if a release should be rejected before scoring.

        Args:
            release: Release dictionary from indexer
            is_single_episode: Whether searching for a single episode
            media_release_date: ISO date string of the media's release/air date
            is_book: True when matching for an ebook/audiobook — disables the
                video-style minimum-size filter (a real EPUB can be 200 KB).

        Returns rejection reason string, or None if release is acceptable.
        """
        title = release.get("title", "")
        size = release.get("size", 0)

        # Reject samples (< 50 MB for video content). Skip for books — eBooks
        # are legitimately tiny and would otherwise be 100% rejected.
        if not is_book and size and 0 < size < cls.MIN_VIDEO_SIZE_BYTES:
            return "too_small_likely_sample"

        # Reject raw disc images
        if cls._RAW_DISK_RE.search(title):
            return "raw_disk_image"

        # Reject multi-season packs when searching for a single episode
        if is_single_episode and cls._MULTI_SEASON_RE.search(title):
            return "multi_season_pack"

        # Reject releases published before the media's release date (minus 14 days buffer)
        if media_release_date:
            publish_date_str = release.get("publish_date") or release.get("pubDate")
            if publish_date_str:
                try:
                    from datetime import datetime, timedelta, timezone

                    # Parse media release date
                    if isinstance(media_release_date, str):
                        media_date = datetime.fromisoformat(
                            media_release_date.replace("Z", "+00:00")
                        ).replace(tzinfo=timezone.utc)
                    else:
                        media_date = media_release_date

                    # Parse publish date (various formats from Newznab)
                    pub_date = None
                    if isinstance(publish_date_str, str):
                        try:
                            pub_date = datetime.fromisoformat(
                                publish_date_str.replace("Z", "+00:00")
                            )
                        except ValueError:
                            from email.utils import parsedate_to_datetime
                            try:
                                pub_date = parsedate_to_datetime(publish_date_str)
                            except (ValueError, TypeError):
                                logger.debug("Could not parse publish date %r", publish_date_str)

                    if pub_date and media_date:
                        if pub_date.tzinfo is None:
                            pub_date = pub_date.replace(tzinfo=timezone.utc)
                        if media_date.tzinfo is None:
                            media_date = media_date.replace(tzinfo=timezone.utc)

                        earliest_allowed = media_date - timedelta(days=14)
                        if pub_date < earliest_allowed:
                            return "release_too_old_for_media"
                except Exception:
                    pass  # Don't reject if date parsing fails

        return None

    @classmethod
    def match_movie_release(
        cls,
        release_title: str,
        movie_title: str,
        movie_year: int | None = None,
        alternate_titles: list[str] | None = None,
        imdb_id: str | None = None,
        release_imdb_id: str | None = None,
    ) -> MatchResult:
        """
        Match a release title against a movie.

        Args:
            release_title: The full release title to match
            movie_title: The movie's title
            movie_year: The movie's release year
            alternate_titles: Alternative titles for the movie
            imdb_id: The movie's IMDB ID
            release_imdb_id: IMDB ID from the release (if provided by indexer)

        Returns:
            MatchResult with match status and score
        """
        # Parse the release title
        parsed = ReleaseParser.parse_movie_release(release_title)
        all_titles = [movie_title] + (alternate_titles or [])

        details = {
            "parsed_title": parsed.title,
            "parsed_year": parsed.year,
            "movie_title": movie_title,
            "movie_year": movie_year,
        }

        # 1. Check IMDB ID match (highest priority)
        if imdb_id and release_imdb_id:
            imdb_normalized = cls._normalize_imdb_id(imdb_id)
            release_imdb_normalized = cls._normalize_imdb_id(release_imdb_id)
            if imdb_normalized == release_imdb_normalized:
                return MatchResult(
                    is_match=True,
                    score=1.0,
                    match_type="id",
                    details={**details, "matched_by": "imdb_id"},
                )

        # Try matching against all titles
        best_match = MatchResult(
            is_match=False, score=0.0, match_type="no_match", details=details
        )

        for title in all_titles:
            match = cls._match_title(
                parsed.title,
                title,
                parsed.year,
                movie_year,
            )
            if match.score > best_match.score:
                best_match = match
                best_match.details = {**details, "matched_title": title}

            # If we got an exact match, no need to continue
            if match.match_type == "exact":
                break

        return best_match

    @classmethod
    def match_book_release(
        cls,
        release_title: str,
        book_title: str,
        author: str | None = None,
    ) -> MatchResult:
        """Match a release title against an ebook/audiobook.

        Indexers return book titles in many shapes — ``Author.Last.First.Title.Words.YEAR.eBook-GROUP``,
        ``Title (Audiobook) [Narrator]``, etc. We strip the common
        format/group tags and accept fuzzy hits on title with optional
        author bonus, similar to how games are matched.
        """
        import re
        clean = release_title
        # Drop format / source tags
        clean = re.sub(
            r"\b(EPUB|MOBI|AZW3|PDF|CBR|CBZ|RETAiL|RETAIL|Audiobook|MP3|M4B|FLAC|Unabridged|Abridged|eBook|ebook)\b",
            " ", clean, flags=re.IGNORECASE,
        )
        # Drop release groups like -NODE, -DiVER, -KAT etc.
        clean = re.sub(r"-[A-Z][A-Za-z0-9]+\s*$", " ", clean)
        # Drop bracketed extras
        clean = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", clean)
        # Year tags inside the release name confuse fuzzy matching slightly,
        # but they help when present, so leave them for the title matcher.
        clean = re.sub(r"[._]+", " ", clean).strip()

        details = {
            "release_title": release_title,
            "cleaned_title": clean,
            "book_title": book_title,
            "author": author,
        }

        match = cls._match_title(clean, book_title, None, None)

        # Author boost: cleaned title contains the author name → strong signal
        if author and author.lower() in clean.lower():
            match.score = max(match.score, 0.7)
            match.is_match = match.is_match or match.score >= 0.6
            details["author_match"] = True

        # Lenient threshold for books — title noise from author/series/year
        # tags often pushes a real match below the default cutoff.
        if not match.is_match and match.score >= 0.55:
            match = MatchResult(
                is_match=True,
                score=match.score,
                match_type="fuzzy",
                details={**details, "note": "lenient book match"},
            )
        elif match.is_match:
            match.details = details

        return match

    @classmethod
    def match_game_release(
        cls,
        release_title: str,
        game_title: str,
        game_year: int | None = None,
    ) -> MatchResult:
        """Match a release title against a game.

        Games use a more lenient matching than movies because:
        - No season/episode semantics
        - Titles often include version numbers, DLC names, platform tags
        - Release groups use different naming conventions (RELOADED, CODEX, GOG, etc.)
        """
        # Strip common game release artifacts for matching
        import re
        clean = release_title
        # Remove version numbers: v1.2.3, Update.v1.0, etc.
        clean = re.sub(r'[._-]v?\d+\.\d+[\.\d]*', ' ', clean)
        # Remove common game group/format tags
        clean = re.sub(r'\b(REPACK|RELOADED|CODEX|GOG|PLAZA|SKIDROW|FitGirl|DODI|RUNE|KaOs|Steam|Rip|Repack|UPDATE|DLC|Bonus|Content|MULTi\d+)\b', ' ', clean, flags=re.IGNORECASE)
        # Remove anything in parentheses (often "From X GB" repack info)
        clean = re.sub(r'\([^)]*\)', ' ', clean)
        # Remove brackets
        clean = re.sub(r'\[[^\]]*\]', ' ', clean)
        # Normalize separators
        clean = re.sub(r'[._-]+', ' ', clean).strip()

        details = {
            "release_title": release_title,
            "cleaned_title": clean,
            "game_title": game_title,
            "game_year": game_year,
        }

        # Use the standard title matcher with the cleaned release title
        match = cls._match_title(
            clean,
            game_title,
            None,  # Don't use year from release (often absent for games)
            game_year,
        )

        # Games get a more lenient fuzzy threshold
        if not match.is_match and match.score >= 0.55:
            match = MatchResult(
                is_match=True,
                score=match.score,
                match_type="fuzzy",
                details={**details, "note": "lenient game match"},
            )
        elif match.is_match:
            match.details = details

        return match

    @classmethod
    def match_episode_release(
        cls,
        release_title: str,
        show_title: str,
        season: int,
        episode: int,
        show_year: int | None = None,
        alternate_titles: list[str] | None = None,
        tvdb_id: str | None = None,
        release_tvdb_id: str | None = None,
    ) -> MatchResult:
        """
        Match a release title against a TV episode.

        Args:
            release_title: The full release title to match
            show_title: The show's title
            season: The season number to match
            episode: The episode number to match
            show_year: The show's premiere year
            alternate_titles: Alternative titles for the show
            tvdb_id: The show's TVDB ID
            release_tvdb_id: TVDB ID from the release (if provided by indexer)

        Returns:
            MatchResult with match status and score
        """
        # Parse the release title
        parsed = ReleaseParser.parse_show_release(release_title)
        all_titles = [show_title] + (alternate_titles or [])

        details = {
            "parsed_title": parsed.title,
            "parsed_season": parsed.season,
            "parsed_episode": parsed.episode,
            "parsed_year": parsed.year,
            "show_title": show_title,
            "expected_season": season,
            "expected_episode": episode,
            "is_season_pack": parsed.is_season_pack,
        }

        # 1. Check TVDB ID match (highest priority if season/episode also match)
        if tvdb_id and release_tvdb_id:
            if str(tvdb_id) == str(release_tvdb_id):
                # Still need to verify season/episode
                if cls._season_episode_matches(
                    parsed.season, parsed.episode, parsed.episode_end, season, episode
                ):
                    return MatchResult(
                        is_match=True,
                        score=1.0,
                        match_type="id",
                        details={**details, "matched_by": "tvdb_id"},
                    )

        # 2. Check season/episode first (must match for any TV release)
        if not cls._season_episode_matches(
            parsed.season, parsed.episode, parsed.episode_end, season, episode
        ):
            # Season/episode doesn't match - not a valid release for this episode
            return MatchResult(
                is_match=False,
                score=0.0,
                match_type="no_match",
                details={
                    **details,
                    "reason": "season/episode mismatch",
                },
            )

        # Season pack handling
        if parsed.is_season_pack:
            if parsed.season == season:
                # Season pack matches - this could be used for the whole season
                return MatchResult(
                    is_match=True,
                    score=0.7,  # Lower score than specific episode releases
                    match_type="season_pack",
                    details={**details, "matched_by": "season_pack"},
                )

        # Try matching against all titles
        best_match = MatchResult(
            is_match=False, score=0.0, match_type="no_match", details=details
        )

        for title in all_titles:
            match = cls._match_title(
                parsed.title,
                title,
                parsed.year,
                show_year,
            )

            # Add bonus for matching season/episode
            if match.is_match:
                match.score = min(1.0, match.score + cls.SEASON_EPISODE_MATCH_BONUS)

            if match.score > best_match.score:
                best_match = match
                best_match.details = {**details, "matched_title": title}

            # If we got an exact match, no need to continue
            if match.match_type == "exact":
                break

        return best_match

    @classmethod
    def match_music_release(
        cls,
        release_title: str,
        artist: str,
        album_title: str | None = None,
        song_title: str | None = None,
        release_year: int | None = None,
    ) -> MatchResult:
        """
        Match a release title against a music item (artist + album/song).

        Args:
            release_title: The full release title to match
            artist: The artist name (mandatory for matching)
            album_title: Album title to match against
            song_title: Song title to match against
            release_year: Year hint for scoring

        Returns:
            MatchResult with match status and score
        """
        from difflib import SequenceMatcher

        parsed = ReleaseParser.parse_music_release(release_title)

        details = {
            "parsed_artist": parsed.artist,
            "parsed_title": parsed.title,
            "parsed_year": parsed.year,
            "expected_artist": artist,
            "expected_album": album_title,
            "expected_song": song_title,
        }

        # Reject releases that are too small (< 1MB — likely not a real music file)
        # This is handled in should_reject_release, not here

        # Normalize names for comparison
        norm_artist = ReleaseParser.normalize_title(artist)
        norm_parsed_artist = ReleaseParser.normalize_title(parsed.artist)

        if not norm_parsed_artist or not norm_artist:
            # Can't determine artist from release title — use title-based matching
            # Match the whole release against "Artist Album/Song"
            target = f"{artist} {album_title or song_title or ''}"
            norm_target = ReleaseParser.normalize_title(target)
            norm_release = ReleaseParser.normalize_title(release_title)

            similarity = SequenceMatcher(None, norm_release, norm_target).ratio()
            if similarity >= cls.FUZZY_THRESHOLD:
                return MatchResult(
                    is_match=True,
                    score=similarity * 0.8,
                    match_type="fuzzy_combined",
                    details={**details, "similarity": similarity},
                )
            return MatchResult(
                is_match=False, score=0.0, match_type="no_match",
                details={**details, "reason": "cannot_parse_artist"},
            )

        # Artist match (mandatory)
        artist_similarity = SequenceMatcher(
            None, norm_parsed_artist, norm_artist
        ).ratio()

        if artist_similarity < cls.FUZZY_THRESHOLD:
            return MatchResult(
                is_match=False, score=0.0, match_type="no_match",
                details={
                    **details,
                    "reason": "artist_mismatch",
                    "artist_similarity": artist_similarity,
                },
            )

        # Artist matches — now check album or song title
        score = 0.0
        match_type = "artist_only"
        match_target = album_title or song_title or ""

        if match_target:
            norm_target = ReleaseParser.normalize_title(match_target)
            norm_parsed_title = ReleaseParser.normalize_title(parsed.title)

            if norm_parsed_title and norm_target:
                # Exact match
                if norm_parsed_title == norm_target:
                    score = 0.95
                    match_type = "exact"
                # Partial match
                elif norm_target in norm_parsed_title or norm_parsed_title in norm_target:
                    score = 0.85
                    match_type = "partial"
                else:
                    # Fuzzy match
                    title_similarity = SequenceMatcher(
                        None, norm_parsed_title, norm_target
                    ).ratio()
                    if title_similarity >= cls.FUZZY_THRESHOLD:
                        score = title_similarity * 0.9
                        match_type = "fuzzy"
                    else:
                        # Artist matches but title doesn't — low score
                        score = artist_similarity * 0.5
                        match_type = "artist_only"
            else:
                score = artist_similarity * 0.6
        else:
            # No title to match — artist-only match
            score = artist_similarity * 0.7
            match_type = "artist_only"

        # Year bonus
        if release_year and parsed.year and release_year == parsed.year:
            score = min(1.0, score + cls.YEAR_MATCH_BONUS)

        return MatchResult(
            is_match=score > 0.0,
            score=score,
            match_type=match_type,
            details={
                **details,
                "artist_similarity": artist_similarity,
                "matched_by": match_type,
            },
        )

    @classmethod
    def _match_title(
        cls,
        release_title: str,
        media_title: str,
        release_year: int | None,
        media_year: int | None,
    ) -> MatchResult:
        """
        Match a parsed release title against a media title.

        Returns the best match result with appropriate score.
        """
        # Normalize both titles
        norm_release = ReleaseParser.normalize_title(release_title)
        norm_media = ReleaseParser.normalize_title(media_title)

        if not norm_release or not norm_media:
            return MatchResult(
                is_match=False,
                score=0.0,
                match_type="no_match",
                details={"reason": "empty title after normalization"},
            )

        # Hard reject: year mismatch when both years are known and
        # the year is NOT part of the media title (e.g. "2001" in "Scrubs"
        # title means wrong series, but "2001" in "2001: A Space Odyssey" is fine)
        if release_year and media_year and release_year != media_year:
            year_in_title = str(media_year) in media_title or str(release_year) in media_title
            if not year_in_title:
                return MatchResult(
                    is_match=False,
                    score=0.0,
                    match_type="no_match",
                    details={
                        "reason": "year_mismatch",
                        "release_year": release_year,
                        "media_year": media_year,
                    },
                )

        # 2. Exact match (case-insensitive, normalized)
        if norm_release == norm_media:
            score = 0.95
            # Year match bonus
            if release_year and media_year and release_year == media_year:
                score = min(1.0, score + cls.YEAR_MATCH_BONUS)
            return MatchResult(
                is_match=True,
                score=score,
                match_type="exact",
                details={
                    "normalized_release": norm_release,
                    "normalized_media": norm_media,
                },
            )

        # 3. Check if one contains the other (for subtitle variations)
        if norm_release in norm_media or norm_media in norm_release:
            score = 0.85
            if release_year and media_year and release_year == media_year:
                score = min(1.0, score + cls.YEAR_MATCH_BONUS)
            return MatchResult(
                is_match=True,
                score=score,
                match_type="partial",
                details={
                    "normalized_release": norm_release,
                    "normalized_media": norm_media,
                },
            )

        # 4. Fuzzy match using sequence similarity
        similarity = SequenceMatcher(None, norm_release, norm_media).ratio()

        if similarity >= cls.FUZZY_THRESHOLD:
            score = similarity * 0.9  # Scale down fuzzy matches slightly
            if release_year and media_year and release_year == media_year:
                score = min(1.0, score + cls.YEAR_MATCH_BONUS)
            return MatchResult(
                is_match=True,
                score=score,
                match_type="fuzzy",
                details={
                    "similarity": similarity,
                    "normalized_release": norm_release,
                    "normalized_media": norm_media,
                },
            )

        # 5. Try with year appended (some shows include year in title)
        if media_year:
            norm_media_with_year = f"{norm_media} {media_year}"
            similarity_with_year = SequenceMatcher(
                None, norm_release, norm_media_with_year
            ).ratio()
            if similarity_with_year >= cls.FUZZY_THRESHOLD:
                return MatchResult(
                    is_match=True,
                    score=similarity_with_year * 0.85,
                    match_type="fuzzy_with_year",
                    details={
                        "similarity": similarity_with_year,
                        "normalized_release": norm_release,
                        "normalized_media_with_year": norm_media_with_year,
                    },
                )

        # No match
        return MatchResult(
            is_match=False,
            score=0.0,
            match_type="no_match",
            details={
                "similarity": similarity,
                "normalized_release": norm_release,
                "normalized_media": norm_media,
            },
        )

    @classmethod
    def _season_episode_matches(
        cls,
        release_season: int | None,
        release_episode: int | None,
        release_episode_end: int | None,
        expected_season: int,
        expected_episode: int,
    ) -> bool:
        """Check if release season/episode matches expected values."""
        if release_season is None:
            return False

        if release_season != expected_season:
            return False

        # For specific episode match
        if release_episode is not None:
            if release_episode_end is not None:
                # Multi-episode release (e.g., S01E01-E03)
                return release_episode <= expected_episode <= release_episode_end
            return release_episode == expected_episode

        # Season pack (no episode number) - matches all episodes in that season
        return True

    @classmethod
    def _normalize_imdb_id(cls, imdb_id: str) -> str:
        """Normalize IMDB ID to consistent format (tt1234567)."""
        if not imdb_id:
            return ""
        # Remove any prefix and ensure tt format
        imdb_id = imdb_id.strip().lower()
        if imdb_id.startswith("tt"):
            return imdb_id
        # Try to extract number and format
        match = re.search(r"(\d+)", imdb_id)
        if match:
            return f"tt{match.group(1).zfill(7)}"
        return imdb_id

    @classmethod
    def filter_matching_releases(
        cls,
        releases: list[dict[str, Any]],
        media_title: str,
        media_year: int | None = None,
        season: int | None = None,
        episode: int | None = None,
        alternate_titles: list[str] | None = None,
        external_ids: dict[str, str] | None = None,
        min_score: float = 0.0,
        media_release_date: str | None = None,
        artist: str | None = None,
        album_title: str | None = None,
        song_title: str | None = None,
        is_game: bool = False,
        is_book: bool = False,
        author: str | None = None,
    ) -> list[tuple[dict[str, Any], MatchResult]]:
        """
        Filter a list of releases to only include matching ones.

        Args:
            releases: List of release dictionaries from indexer
            media_title: The media item's title
            media_year: The media item's year
            season: Season number (for TV shows)
            episode: Episode number (for TV shows)
            alternate_titles: Alternative titles
            external_ids: Dict of external IDs (imdb_id, tvdb_id, etc.)
            min_score: Minimum match score to include (default 0, include all matches)

        Returns:
            List of (release, MatchResult) tuples for matching releases, sorted by score
        """
        external_ids = external_ids or {}
        matching = []

        is_single_episode = season is not None and episode is not None

        for release in releases:
            release_title = release.get("title", "")
            if not release_title:
                continue

            # Pre-filter: reject obviously bad releases before expensive matching
            # Skip rejection for games (ISOs are valid, no video size minimums)
            if not is_game:
                rejection = cls.should_reject_release(
                    release, is_single_episode, media_release_date,
                    is_book=is_book,
                )
                if rejection:
                    logger.info("Rejected release '%s': %s", release_title, rejection)
                    continue

            # Get external IDs from release if available
            release_imdb = release.get("imdb_id") or release.get("imdbid")
            release_tvdb = release.get("tvdb_id") or release.get("tvdbid")

            if is_book:
                match = cls.match_book_release(
                    release_title=release_title,
                    book_title=media_title,
                    author=author,
                )
            elif is_game:
                # Game matching — title-based, lenient
                match = cls.match_game_release(
                    release_title=release_title,
                    game_title=media_title,
                    game_year=media_year,
                )
            elif artist is not None:
                # Music matching
                match = cls.match_music_release(
                    release_title=release_title,
                    artist=artist,
                    album_title=album_title,
                    song_title=song_title,
                    release_year=media_year,
                )
            elif season is not None and episode is not None:
                # TV show episode matching
                match = cls.match_episode_release(
                    release_title=release_title,
                    show_title=media_title,
                    season=season,
                    episode=episode,
                    show_year=media_year,
                    alternate_titles=alternate_titles,
                    tvdb_id=external_ids.get("tvdb"),
                    release_tvdb_id=release_tvdb,
                )
            else:
                # Movie matching
                match = cls.match_movie_release(
                    release_title=release_title,
                    movie_title=media_title,
                    movie_year=media_year,
                    alternate_titles=alternate_titles,
                    imdb_id=external_ids.get("imdb"),
                    release_imdb_id=release_imdb,
                )

            if match.is_match and match.score >= min_score:
                matching.append((release, match))
                logger.debug(
                    f"Release matched: {release_title} -> {match.match_type} "
                    f"(score: {match.score:.2f})"
                )
            else:
                logger.debug(
                    f"Release rejected: {release_title} -> {match.match_type} "
                    f"(score: {match.score:.2f})"
                )

        # Sort by match score (highest first)
        matching.sort(key=lambda x: x[1].score, reverse=True)

        return matching
