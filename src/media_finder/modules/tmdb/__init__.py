"""TMDB metadata integration with package-owned retention policy."""

import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from email.utils import format_datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
from dateutil.relativedelta import relativedelta
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from ...sdk.errors import ModuleError
from ...sdk.protocols import JsonTransport
from ...sdk.redaction import safe_url_origin
from ...sdk.settings import EnvReference
from ...sdk.types import (
    Artwork,
    Attribution,
    Episode,
    ExportHeader,
    ExportWarning,
    MediaKind,
    MetadataSearchResult,
    ModuleManifest,
    NormalizedMetadata,
    Provenance,
    Rating,
    RetentionAction,
    RetentionActionKind,
    RetentionPolicy,
    Season,
)

TMDB_ENDPOINT = re.compile(
    r"^(?:/configuration|/search/(?:movie|tv)|/(?:movie|tv)/[0-9]{1,20}|/tv/[0-9]{1,20}/season/[0-9]{1,4})$"
)
TMDB_ID = re.compile(r"^[0-9]{1,20}$")
SAFE_BASE_PATH = re.compile(r"^/[A-Za-z0-9._~/-]*$")
SECRET_PATH_MARKERS = ("credential", "passkey", "secret", "session", "token")
IMAGE_PATH = re.compile(r"^/[A-Za-z0-9._/-]+$")
IMAGE_BASE_URL = "https://image.tmdb.org/t/p/original"


class TmdbConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", validate_default=True)

    api_token: EnvReference = Field(
        title="module.tmdb.settings.api_token", json_schema_extra={"secret": True, "order": 1}
    )
    base_url: HttpUrl = Field(
        default=HttpUrl("https://api.themoviedb.org/3"),
        title="module.tmdb.settings.base_url",
        json_schema_extra={"order": 2},
    )

    @field_validator("api_token", mode="before")
    @classmethod
    def parse_reference(cls, value: object) -> object:
        return EnvReference(value=value) if isinstance(value, str) else value

    @field_validator("base_url")
    @classmethod
    def require_safe_endpoint(cls, value: HttpUrl) -> HttpUrl:
        path = value.path or "/"
        secret_path = any(
            marker in segment.casefold()
            for segment in path.split("/")
            for marker in SECRET_PATH_MARKERS
        )
        if (
            value.username
            or value.password
            or value.query
            or value.fragment
            or not SAFE_BASE_PATH.fullmatch(path)
            or secret_path
        ):
            raise ValueError("tmdb_base_url_invalid")
        return value


class HttpxTmdbTransport:
    """TMDB JSON transport resolving the bearer token for each request."""

    def __init__(
        self,
        base_url: str,
        api_token_ref: str,
        secret_resolver: Callable[[str], str],
        client: httpx.Client,
    ) -> None:
        self._base_url = _validated_tmdb_base_url(base_url)
        self._api_token_ref = EnvReference(value=api_token_ref).value
        self._secret_resolver = secret_resolver
        self._client = client

    def get_json(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        if TMDB_ENDPOINT.fullmatch(path) is None:
            raise ValueError("tmdb_endpoint_invalid")
        response = self._client.get(
            f"{self._base_url}{path}",
            params=params,
            headers={"Authorization": f"Bearer {self._secret_resolver(self._api_token_ref)}"},
            follow_redirects=False,
        )
        if response.is_redirect:
            raise RuntimeError("TMDB redirect rejected")
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("TMDB response is invalid")
        return payload


class TmdbProvider:
    manifest = ModuleManifest(
        key="tmdb",
        version="1.0.0",
        contract_version="1",
        name_key="module.tmdb.name",
        capabilities=frozenset({"movie", "series", "search", "localized_metadata", "retention"}),
        translation_keys={
            "module.tmdb.name": "TMDB",
            "module.tmdb.settings.api_token": "API token environment reference",
            "module.tmdb.settings.base_url": "API base URL",
        },
    )
    config_model = TmdbConfig

    def __init__(self, config: TmdbConfig | None, transport: JsonTransport | None) -> None:
        self.config = config
        self.transport = transport

    @classmethod
    def retention_only(cls) -> "TmdbProvider":
        return cls(None, None)

    def validate_config(self) -> None:
        if self.config is None:
            raise ModuleError(
                code="metadata_provider_not_configured",
                message="The metadata provider is not configured.",
            )
        TmdbConfig.model_validate(self.config.model_dump())
        if self.transport is not None:
            self.transport.get_json("/configuration", {})

    def search(self, query: str, locale: str) -> list[MetadataSearchResult]:
        results: list[MetadataSearchResult] = []
        searches = (
            ("/search/movie", MediaKind.MOVIE, "title", "release_date"),
            ("/search/tv", MediaKind.SERIES, "name", "first_air_date"),
        )
        for path, kind, title_field, date_field in searches:
            payload = self._request(path, {"query": query, "language": locale})
            for item in payload.get("results", []):
                release = item.get(date_field) or ""
                results.append(
                    MetadataSearchResult(
                        provider_key="tmdb",
                        external_id=str(item["id"]),
                        kind=kind,
                        title=str(item[title_field]),
                        year=int(release[:4]) if len(release) >= 4 else None,
                        locale=locale,
                    )
                )
        return results

    def fetch(self, kind: str, external_id: str, locale: str) -> dict[str, Any]:
        if kind not in {MediaKind.MOVIE.value, MediaKind.SERIES.value}:
            raise ModuleError(code="metadata_kind_invalid", message="The media kind is invalid.")
        if TMDB_ID.fullmatch(external_id) is None:
            raise ModuleError(
                code="metadata_identity_invalid", message="The provider identity is invalid."
            )
        path_kind = "tv" if kind == "series" else "movie"
        payload = self._request(f"/{path_kind}/{external_id}", {"language": locale})
        if kind == MediaKind.SERIES.value:
            season_details: list[dict[str, Any]] = []
            for summary in payload.get("seasons", []):
                if not isinstance(summary, dict) or not isinstance(
                    summary.get("season_number"), int
                ):
                    continue
                number = summary["season_number"]
                if number < 0 or number > 9999:
                    continue
                detail = self._request(f"/tv/{external_id}/season/{number}", {"language": locale})
                season_details.append(detail)
            payload = dict(payload)
            payload["seasons"] = season_details
        return payload

    def normalize(
        self, payload: dict[str, Any], kind: str, external_id: str, locale: str
    ) -> NormalizedMetadata:
        path_kind = "tv" if kind == "series" else "movie"
        release = payload.get("release_date") or payload.get("first_air_date")
        title = payload.get("title") or payload.get("name")
        seasons = tuple(
            Season(
                number=int(season["season_number"]),
                title=season.get("name"),
                provider_ids={"tmdb": str(season["id"])} if season.get("id") else {},
                episodes=tuple(
                    Episode(
                        number=int(episode["episode_number"]),
                        title=episode.get("name") or f"Episode {episode['episode_number']}",
                        plot=episode.get("overview") or None,
                        air_date=date.fromisoformat(episode["air_date"])
                        if episode.get("air_date")
                        else None,
                        runtime_minutes=episode.get("runtime") or None,
                        provider_ids={"tmdb": str(episode["id"])} if episode.get("id") else {},
                        ordering=int(episode.get("order", episode["episode_number"])),
                    )
                    for episode in season.get("episodes", [])
                ),
            )
            for season in payload.get("seasons", [])
        )
        return NormalizedMetadata(
            kind=MediaKind.SERIES if path_kind == "tv" else MediaKind.MOVIE,
            titles={locale: str(title or external_id)},
            original_title=payload.get("original_title") or payload.get("original_name"),
            year=int(release[:4]) if release else None,
            plot=payload.get("overview") or None,
            release_date=release or None,
            runtime_minutes=payload.get("runtime") or None,
            provider_ids={"tmdb": str(payload["id"])},
            ratings=(Rating(source="tmdb", value=float(payload["vote_average"])),)
            if payload.get("vote_average") is not None
            else (),
            genres=tuple(value["name"] for value in payload.get("genres", [])),
            countries=tuple(value["name"] for value in payload.get("production_countries", [])),
            studios=tuple(value["name"] for value in payload.get("production_companies", [])),
            artwork=tuple(
                artwork
                for artwork in (
                    self._artwork("poster", payload.get("poster_path"), locale),
                    self._artwork("backdrop", payload.get("backdrop_path"), locale),
                )
                if artwork is not None
            ),
            seasons=seasons,
            provenance=Provenance(
                provider_key="tmdb",
                external_id=str(payload["id"]),
                locale=locale,
                fetched_at=datetime.now(UTC),
                source_label="TMDB",
            ),
            completeness=self._completeness(payload),
            structural_quality=1.0,
        )

    def attribution(self) -> Attribution:
        return Attribution.model_validate(
            {
                "provider_key": "tmdb",
                "notice": (
                    "This product uses the TMDB API but is not endorsed or certified by TMDB."
                ),
                "url": "https://www.themoviedb.org/",
            }
        )

    def retention_for(self, created_at: datetime) -> RetentionPolicy:
        return RetentionPolicy(
            refresh_after=created_at + relativedelta(months=5),
            expires_at=created_at + relativedelta(months=6),
        )

    def plan_retention(self, policy: RetentionPolicy, now: datetime) -> RetentionAction:
        current = self._aware(now)
        assert current is not None
        expires = self._aware(policy.expires_at)
        refresh = self._aware(policy.refresh_after)
        if expires is not None and current >= expires:
            return RetentionAction(kind=RetentionActionKind.PURGE, mandatory=True)
        if refresh is not None and current >= refresh:
            return RetentionAction(kind=RetentionActionKind.REFRESH)
        return RetentionAction(kind=RetentionActionKind.NONE)

    def export_warning(self, policy: RetentionPolicy, now: datetime) -> ExportWarning | None:
        del now
        expires = self._aware(policy.expires_at)
        if expires is None:
            return None
        return ExportWarning(
            headers=(
                ExportHeader(
                    name="Warning",
                    value=('299 Media Finder "Provider-derived metadata has a retention deadline"'),
                ),
                ExportHeader(name="Sunset", value=format_datetime(expires, usegmt=True)),
                ExportHeader(name="X-Media-Finder-Metadata-Expires", value=expires.isoformat()),
            )
        )

    def _request(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        if self.transport is None:
            raise ModuleError(
                code="metadata_provider_not_configured",
                message="The metadata provider is not configured.",
            )
        try:
            return self.transport.get_json(path, params)
        except Exception as error:
            details = {"provider": self.manifest.key}
            try:
                origin = safe_url_origin(str(error))
            except Exception:
                origin = None
            if origin is not None:
                details["upstream_origin"] = origin
            raise ModuleError(
                code="metadata_provider_unavailable",
                message="The metadata provider is temporarily unavailable.",
                safe_details=details,
            ) from None

    @staticmethod
    def _aware(value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

    @staticmethod
    def _completeness(payload: dict[str, Any]) -> float:
        present = sum(
            bool(payload.get(key))
            for key in ("title", "name", "overview", "release_date", "first_air_date", "runtime")
        )
        return min(1.0, present / 4)

    @staticmethod
    def _artwork(kind: str, path: object, locale: str) -> Artwork | None:
        if not isinstance(path, str) or IMAGE_PATH.fullmatch(path) is None or ".." in path:
            return None
        return Artwork(kind=kind, url=HttpUrl(f"{IMAGE_BASE_URL}{path}"), language=locale)


def _validated_tmdb_base_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        path = parsed.path or "/"
        secret_path = any(
            marker in segment.casefold()
            for segment in path.split("/")
            for marker in SECRET_PATH_MARKERS
        )
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or SAFE_BASE_PATH.fullmatch(path) is None
            or secret_path
        ):
            raise ValueError
        _ = parsed.port
    except (UnicodeError, ValueError):
        raise ValueError("tmdb_base_url_invalid") from None
    return value.rstrip("/")


__all__ = ["HttpxTmdbTransport", "TmdbConfig", "TmdbProvider"]
