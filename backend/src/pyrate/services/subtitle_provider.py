"""Subtitle provider search helpers."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from pyrate.models.media import MediaItem


class SubtitleProviderError(ValueError):
    """Raised when a subtitle provider request cannot be satisfied."""


def load_media_extra_data(media_item: MediaItem) -> dict[str, Any]:
    """Return parsed media ``extra_data`` as a dictionary."""
    if not media_item.extra_data:
        return {}
    try:
        data = json.loads(media_item.extra_data)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


class SubtitleProviderService:
    """Search configured subtitle provider results for a media item.

    The built-in provider reads normalized provider candidates from media
    metadata. Network-backed providers can later implement the same result
    shape without changing the API contract.
    """

    _RESULT_KEYS = ("remote_subtitles", "subtitle_provider_results")

    def __init__(
        self,
        enabled_providers: list[str] | None = None,
        provider_urls: dict[str, str] | None = None,
        provider_api_keys: dict[str, str] | None = None,
        client: httpx.AsyncClient | None = None,
    ):
        self.enabled_providers = {
            provider.strip().lower()
            for provider in (enabled_providers or [])
            if provider and provider.strip()
        }
        self.provider_urls = {
            provider.strip().lower(): url.strip()
            for provider, url in (provider_urls or {}).items()
            if provider and isinstance(url, str) and url.strip()
        }
        self.provider_api_keys = {
            provider.strip().lower(): api_key.strip()
            for provider, api_key in (provider_api_keys or {}).items()
            if provider and isinstance(api_key, str) and api_key.strip()
        }
        self.client = client

    def search(
        self,
        media_item: MediaItem,
        *,
        language: str | None = None,
        provider: str | None = None,
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return subtitle candidates available through configured providers."""
        provider_filter = provider.strip().lower() if provider else None
        language_filter = language.strip().lower() if language else None
        query_filter = query.strip().lower() if query else None

        results: list[dict[str, Any]] = []
        for raw in self._raw_candidates(media_item):
            normalized = self._normalize_candidate(raw)
            if not normalized:
                continue

            candidate_provider = normalized["provider"].lower()
            if self.enabled_providers and candidate_provider not in self.enabled_providers:
                continue
            if provider_filter and candidate_provider != provider_filter:
                continue
            if language_filter and normalized["language"].lower() != language_filter:
                continue
            if query_filter and query_filter not in " ".join(
                str(normalized.get(key) or "").lower()
                for key in ("title", "file_name", "release_group")
            ):
                continue
            self._apply_candidate_ranking(
                normalized,
                media_item,
                language_filter=language_filter,
                query_filter=query_filter,
            )
            results.append(normalized)

        return sorted(
            results,
            key=self._sort_key,
            reverse=True,
        )

    def get_candidate(
        self,
        media_item: MediaItem,
        *,
        provider: str,
        provider_id: str,
    ) -> dict[str, Any]:
        """Return one provider candidate by provider/id."""
        provider_key = provider.strip().lower()
        provider_id_key = provider_id.strip()
        for candidate in self.search(media_item, provider=provider_key):
            if candidate["provider_id"] == provider_id_key:
                return candidate
        raise SubtitleProviderError("Subtitle provider result not found")

    async def search_async(
        self,
        media_item: MediaItem,
        *,
        language: str | None = None,
        provider: str | None = None,
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return metadata and network-backed subtitle candidates."""
        results = self.search(
            media_item,
            language=language,
            provider=provider,
            query=query,
        )
        results.extend(
            await self._network_candidates(
                media_item,
                language=language,
                provider=provider,
                query=query,
            )
        )
        deduped: dict[tuple[str, str], dict[str, Any]] = {}
        language_filter = language.strip().lower() if language else None
        query_filter = query.strip().lower() if query else None
        for result in results:
            self._apply_candidate_ranking(
                result,
                media_item,
                language_filter=language_filter,
                query_filter=query_filter,
            )
            key = (result["provider"].lower(), result["provider_id"])
            existing = deduped.get(key)
            if existing is None or self._sort_key(result) > self._sort_key(existing):
                deduped[key] = result
        return sorted(
            deduped.values(),
            key=self._sort_key,
            reverse=True,
        )

    async def get_candidate_async(
        self,
        media_item: MediaItem,
        *,
        provider: str,
        provider_id: str,
    ) -> dict[str, Any]:
        """Return one metadata or network provider candidate by provider/id."""
        provider_key = provider.strip().lower()
        provider_id_key = provider_id.strip()
        for candidate in await self.search_async(media_item, provider=provider_key):
            if candidate["provider_id"] == provider_id_key:
                return candidate
        raise SubtitleProviderError("Subtitle provider result not found")

    async def _network_candidates(
        self,
        media_item: MediaItem,
        *,
        language: str | None,
        provider: str | None,
        query: str | None,
    ) -> list[dict[str, Any]]:
        provider_filter = provider.strip().lower() if provider else None
        provider_urls = {
            key: url
            for key, url in self.provider_urls.items()
            if (not self.enabled_providers or key in self.enabled_providers)
            and (not provider_filter or key == provider_filter)
        }
        if not provider_urls:
            return []

        close_client = False
        client = self.client
        if client is None:
            client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))
            close_client = True

        try:
            results: list[dict[str, Any]] = []
            for provider_name, url in provider_urls.items():
                try:
                    response = await client.get(
                        url,
                        params=self._network_search_params(
                            provider_name,
                            media_item,
                            language=language,
                            query=query,
                        ),
                        headers=self._network_headers(provider_name),
                    )
                    response.raise_for_status()
                    payload = response.json()
                except Exception as exc:
                    raise SubtitleProviderError(
                        f"Subtitle provider '{provider_name}' request failed: {exc}"
                    ) from exc

                for raw in self._network_payload_candidates(provider_name, payload):
                    normalized = self._normalize_candidate(raw)
                    if not normalized:
                        continue
                    if language and normalized["language"].lower() != language.lower():
                        continue
                    self._apply_candidate_ranking(
                        normalized,
                        media_item,
                        language_filter=language.strip().lower() if language else None,
                        query_filter=query.strip().lower() if query else None,
                    )
                    results.append(normalized)
            return results
        finally:
            if close_client:
                await client.aclose()

    def _network_search_params(
        self,
        provider_name: str,
        media_item: MediaItem,
        *,
        language: str | None,
        query: str | None,
    ) -> dict[str, Any]:
        year = media_item.release_date.year if media_item.release_date else None
        if provider_name == "opensubtitles":
            media_type = media_item.media_type.value.lower()
            subtitle_type = "episode" if media_type in {"shows", "episodes"} else "movie"
            return {
                "query": query or media_item.title,
                "languages": language,
                "year": year,
                "type": subtitle_type,
            }
        return {
            "title": media_item.title,
            "media_type": media_item.media_type.value,
            "year": year,
            "language": language,
            "query": query,
        }

    def _network_headers(self, provider_name: str) -> dict[str, str] | None:
        api_key = self.provider_api_keys.get(provider_name)
        if provider_name == "opensubtitles" and api_key:
            return {"Api-Key": api_key}
        return None

    def _download_url(self, provider_name: str) -> str | None:
        provider_url = self.provider_urls.get(provider_name)
        if not provider_url:
            return None
        if provider_name != "opensubtitles":
            return provider_url
        parsed = urlsplit(provider_url)
        path = parsed.path.rstrip("/")
        if path.endswith("/subtitles"):
            path = path[: -len("/subtitles")]
        return urlunsplit((parsed.scheme, parsed.netloc, f"{path}/download", "", ""))

    async def resolve_download_async(self, candidate: dict[str, Any]) -> dict[str, Any]:
        """Resolve provider-specific download metadata for a normalized candidate."""
        provider_name = str(candidate.get("provider") or "").strip().lower()
        if provider_name != "opensubtitles":
            return candidate

        download_url = self._download_url(provider_name)
        if not download_url:
            return candidate

        close_client = False
        client = self.client
        if client is None:
            client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))
            close_client = True

        try:
            try:
                file_id = int(str(candidate["provider_id"]))
            except (TypeError, ValueError) as exc:
                raise SubtitleProviderError(
                    "OpenSubtitles download requires numeric provider_id"
                ) from exc
            try:
                response = await client.post(
                    download_url,
                    json={"file_id": file_id},
                    headers=self._network_headers(provider_name),
                )
                response.raise_for_status()
                payload = response.json()
            except Exception as exc:
                raise SubtitleProviderError(
                    f"OpenSubtitles download request failed: {exc}"
                ) from exc
        finally:
            if close_client:
                await client.aclose()

        if not isinstance(payload, dict):
            raise SubtitleProviderError("Invalid OpenSubtitles download response")
        resolved = dict(candidate)
        link = payload.get("link")
        if isinstance(link, str) and link:
            resolved["url"] = link
        file_name = payload.get("file_name")
        if isinstance(file_name, str) and file_name:
            resolved["file_name"] = file_name
            if "." in file_name:
                resolved["format"] = file_name.rsplit(".", 1)[-1]
        return resolved

    def _network_payload_candidates(
        self,
        provider_name: str,
        payload: Any,
    ) -> list[dict[str, Any]]:
        if provider_name == "opensubtitles":
            return self._opensubtitles_candidates(payload)

        raw_items = payload.get("items") if isinstance(payload, dict) else payload
        if not isinstance(raw_items, list):
            return []
        candidates: list[dict[str, Any]] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            raw.setdefault("provider", provider_name)
            candidates.append(raw)
        return candidates

    def _opensubtitles_candidates(self, payload: Any) -> list[dict[str, Any]]:
        raw_items = payload.get("data") if isinstance(payload, dict) else payload
        if not isinstance(raw_items, list):
            return []

        candidates: list[dict[str, Any]] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            attrs = raw.get("attributes")
            if not isinstance(attrs, dict):
                attrs = {}
            files = attrs.get("files")
            file_info = files[0] if isinstance(files, list) and files else {}
            if not isinstance(file_info, dict):
                file_info = {}

            file_id = file_info.get("file_id") or raw.get("id")
            language = attrs.get("language") or attrs.get("language_name")
            if not file_id or not language:
                continue
            candidates.append(
                {
                    "provider": "opensubtitles",
                    "provider_id": str(file_id),
                    "language": language,
                    "title": attrs.get("feature_details", {}).get("title")
                    if isinstance(attrs.get("feature_details"), dict)
                    else attrs.get("release"),
                    "file_name": file_info.get("file_name") or attrs.get("subtitle_id"),
                    "release_group": attrs.get("release"),
                    "format": file_info.get("file_name", "").rsplit(".", 1)[-1]
                    if isinstance(file_info.get("file_name"), str)
                    and "." in file_info.get("file_name", "")
                    else None,
                    "score": attrs.get("ratings"),
                    "downloads": attrs.get("download_count"),
                    "is_hearing_impaired": attrs.get("hearing_impaired"),
                    "url": attrs.get("url"),
                }
            )
        return candidates

    def _raw_candidates(self, media_item: MediaItem) -> list[dict[str, Any]]:
        extra_data = load_media_extra_data(media_item)
        candidates: list[dict[str, Any]] = []
        for key in self._RESULT_KEYS:
            raw_candidates = extra_data.get(key)
            if not isinstance(raw_candidates, list):
                continue
            candidates.extend(
                raw for raw in raw_candidates if isinstance(raw, dict)
            )
        return candidates

    @staticmethod
    def _normalize_candidate(raw: dict[str, Any]) -> dict[str, Any] | None:
        language = raw.get("language") or raw.get("lang")
        provider_id = raw.get("provider_id") or raw.get("id") or raw.get("guid")
        if not isinstance(language, str) or not language.strip():
            return None
        if not provider_id:
            return None

        provider = raw.get("provider") if isinstance(raw.get("provider"), str) else None
        title = raw.get("title") if isinstance(raw.get("title"), str) else None
        file_name = raw.get("file_name") if isinstance(raw.get("file_name"), str) else None
        release_group = (
            raw.get("release_group") if isinstance(raw.get("release_group"), str) else None
        )
        subtitle_format = raw.get("format") if isinstance(raw.get("format"), str) else None
        path = raw.get("path") if isinstance(raw.get("path"), str) else None
        url = raw.get("url") if isinstance(raw.get("url"), str) else None

        score = raw.get("score")
        if not isinstance(score, (int, float)):
            score = None

        downloads = raw.get("downloads")
        if not isinstance(downloads, int):
            downloads = None

        return {
            "provider": (provider or "metadata").strip(),
            "provider_id": str(provider_id),
            "language": language.strip(),
            "title": title,
            "file_name": file_name,
            "release_group": release_group,
            "format": subtitle_format,
            "path": path,
            "url": url,
            "score": score,
            "downloads": downloads,
            "is_forced": bool(raw.get("is_forced") or raw.get("forced")),
            "is_hearing_impaired": bool(
                raw.get("is_hearing_impaired") or raw.get("hearing_impaired")
            ),
        }

    @staticmethod
    def _sort_key(candidate: dict[str, Any]) -> tuple[float, float, int]:
        match_score = candidate.get("match_score")
        provider_score = candidate.get("score")
        downloads = candidate.get("downloads")
        return (
            float(match_score) if isinstance(match_score, (int, float)) else 0.0,
            float(provider_score) if isinstance(provider_score, (int, float)) else 0.0,
            downloads if isinstance(downloads, int) else 0,
        )

    def _apply_candidate_ranking(
        self,
        candidate: dict[str, Any],
        media_item: MediaItem,
        *,
        language_filter: str | None,
        query_filter: str | None,
    ) -> None:
        score = (
            float(candidate["score"])
            if isinstance(candidate.get("score"), (int, float))
            else 0.0
        )
        reasons: list[str] = []

        language = str(candidate.get("language") or "").strip().lower()
        if language_filter and language == language_filter:
            score += 25
            reasons.append("language")

        title_tokens = " ".join(
            str(candidate.get(key) or "").lower()
            for key in ("title", "file_name", "release_group")
        )
        item_title = (media_item.title or "").strip().lower()
        if item_title and item_title in title_tokens:
            score += 10
            reasons.append("title")
        if query_filter and query_filter in title_tokens:
            score += 8
            reasons.append("query")

        downloads = candidate.get("downloads")
        if isinstance(downloads, int) and downloads > 0:
            score += min(downloads / 1000, 10)
            reasons.append("downloads")

        if candidate.get("is_forced"):
            score -= 15
            reasons.append("forced_penalty")
        if candidate.get("is_hearing_impaired") and query_filter not in {
            "sdh",
            "hearing impaired",
            "hearing_impaired",
        }:
            score -= 2
            reasons.append("hearing_impaired_penalty")

        candidate["match_score"] = round(score, 2)
        candidate["match_reasons"] = reasons
