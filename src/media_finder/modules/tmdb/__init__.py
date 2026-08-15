"""TMDB metadata integration with package-owned retention policy."""

from datetime import UTC, date, datetime
from typing import Any

from dateutil.relativedelta import relativedelta
from pydantic import BaseModel, Field, field_validator

from ...config import EnvReference
from ...sdk.protocols import JsonTransport
from ...sdk.types import (
    Attribution,
    Episode,
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


class TmdbConfig(BaseModel):
    api_token: EnvReference = Field(
        title="module.tmdb.settings.api_token", json_schema_extra={"secret": True, "order": 1}
    )
    base_url: str = Field(
        default="https://api.themoviedb.org/3",
        title="module.tmdb.settings.base_url",
        json_schema_extra={"order": 2},
    )

    @field_validator("api_token", mode="before")
    @classmethod
    def parse_reference(cls, value: object) -> object:
        return EnvReference(value=value) if isinstance(value, str) else value


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

    def __init__(self, config: TmdbConfig, transport: JsonTransport) -> None:
        self.config = config
        self.transport = transport

    def validate_config(self) -> None:
        TmdbConfig.model_validate(self.config.model_dump())

    def search(self, query: str, locale: str) -> list[MetadataSearchResult]:
        payload = self.transport.get_json("/search/movie", {"query": query, "language": locale})
        results: list[MetadataSearchResult] = []
        for item in payload.get("results", []):
            release = item.get("release_date") or ""
            results.append(
                MetadataSearchResult(
                    provider_key="tmdb",
                    external_id=str(item["id"]),
                    kind=MediaKind.MOVIE,
                    title=item["title"],
                    year=int(release[:4]) if len(release) >= 4 else None,
                    locale=locale,
                )
            )
        return results

    def fetch(self, kind: str, external_id: str, locale: str) -> NormalizedMetadata:
        path_kind = "tv" if kind == "series" else "movie"
        payload = self.transport.get_json(f"/{path_kind}/{external_id}", {"language": locale})
        return self.normalize(payload, kind, external_id, locale)

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


__all__ = ["TmdbConfig", "TmdbProvider"]
