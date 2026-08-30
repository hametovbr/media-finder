"""TMDB metadata retrieval capability."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime

from media_finder_sdk import (
    MediaKind,
    MetadataIdentity,
    MetadataSearchQuery,
    MetadataSearchResult,
    ModuleError,
    ModuleFailureCategory,
    NormalizedMetadata,
    ProviderPayload,
)
from pydantic import ValidationError

from .normalization import normalize_payload, search_poster_url
from .transport import TmdbEndpoint, TmdbTransport

_MAX_SERIES_SEASONS = 100


class TmdbProvider:
    def __init__(self, transport: TmdbTransport, clock: Callable[[], datetime]) -> None:
        self._transport = transport
        self._clock = clock
        self._closed = False

    def validate(self) -> None:
        self._require_open()
        self._request(TmdbEndpoint.configuration(), {})

    def search(self, query: MetadataSearchQuery) -> tuple[MetadataSearchResult, ...]:
        self._require_open()
        results: list[MetadataSearchResult] = []
        searches = (
            (MediaKind.MOVIE, TmdbEndpoint.search_movie(), "title", "release_date"),
            (MediaKind.SERIES, TmdbEndpoint.search_series(), "name", "first_air_date"),
        )
        for kind, endpoint, title_field, date_field in searches:
            if kind not in query.media_kinds:
                continue
            payload = self._request(
                endpoint,
                {"query": query.query, "language": query.locale},
            )
            raw_results = payload.get("results", ())
            if not isinstance(raw_results, Sequence) or isinstance(raw_results, str | bytes):
                continue
            for item in raw_results:
                if not isinstance(item, Mapping):
                    continue
                title = item.get(title_field)
                external_id = item.get("id")
                if title is None or external_id is None:
                    continue
                release = item.get(date_field)
                release_text = release if isinstance(release, str) else ""
                overview = item.get("overview")
                try:
                    result = MetadataSearchResult(
                        provider_id="tmdb",
                        external_id=str(external_id),
                        media_kind=kind,
                        title=str(title),
                        year=int(release_text[:4]) if len(release_text) >= 4 else None,
                        locale=query.locale,
                        description=(overview if isinstance(overview, str) and overview else None),
                        poster_url=search_poster_url(item.get("poster_path")),
                    )
                except (TypeError, ValueError, ValidationError):
                    raise ModuleError(
                        category=ModuleFailureCategory.UNAVAILABLE,
                        code="metadata_provider_unavailable",
                    ) from None
                results.append(result)
                if len(results) >= query.limit:
                    return tuple(results)
        return tuple(results)

    def fetch(self, identity: MetadataIdentity) -> ProviderPayload:
        self._require_open()
        self._validate_identity(identity)
        endpoint = (
            TmdbEndpoint.movie(identity.external_id)
            if identity.media_kind is MediaKind.MOVIE
            else TmdbEndpoint.series(identity.external_id)
        )
        payload = self._request(endpoint, {"language": identity.locale})
        if identity.media_kind is MediaKind.SERIES:
            details: list[dict[str, object]] = []
            summaries = payload.get("seasons", ())
            if isinstance(summaries, Sequence) and not isinstance(summaries, str | bytes):
                season_numbers: list[int] = []
                seen_numbers: set[int] = set()
                for summary in summaries:
                    if not isinstance(summary, Mapping):
                        continue
                    number = summary.get("season_number")
                    if not isinstance(number, int) or number < 0 or number > 9999:
                        continue
                    if number in seen_numbers:
                        continue
                    seen_numbers.add(number)
                    season_numbers.append(number)
                if len(season_numbers) > _MAX_SERIES_SEASONS:
                    raise ModuleError(
                        category=ModuleFailureCategory.UNAVAILABLE,
                        code="metadata_provider_unavailable",
                    )
                for number in season_numbers:
                    details.append(
                        self._request(
                            TmdbEndpoint.season(identity.external_id, number),
                            {"language": identity.locale},
                        )
                    )
            payload = dict(payload)
            payload["seasons"] = details
        return ProviderPayload.model_validate({"data": payload})

    def normalize(
        self,
        payload: ProviderPayload,
        identity: MetadataIdentity,
    ) -> NormalizedMetadata:
        self._require_open()
        self._validate_identity(identity)
        return normalize_payload(payload, identity, self._clock())

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._transport.close()

    def _request(self, endpoint: TmdbEndpoint, params: dict[str, str]) -> dict[str, object]:
        try:
            return self._transport.get_json(endpoint, params)
        except ModuleError:
            raise
        except Exception:
            raise ModuleError(
                category=ModuleFailureCategory.UNAVAILABLE,
                code="metadata_provider_unavailable",
            ) from None

    @staticmethod
    def _validate_identity(identity: MetadataIdentity) -> None:
        if identity.provider_id != "tmdb":
            raise ModuleError(
                category=ModuleFailureCategory.INVALID_IDENTITY,
                code="metadata_identity_invalid",
            )
        try:
            int(identity.external_id)
            if not identity.external_id.isascii() or not identity.external_id.isdigit():
                raise ValueError
            if len(identity.external_id) > 20:
                raise ValueError
        except ValueError:
            raise ModuleError(
                category=ModuleFailureCategory.INVALID_IDENTITY,
                code="metadata_identity_invalid",
            ) from None

    def _require_open(self) -> None:
        if self._closed:
            raise ModuleError(
                category=ModuleFailureCategory.UNAVAILABLE,
                code="metadata_provider_closed",
            )


__all__: list[str] = []
