"""Pure Manual metadata validation and normalization module."""

import csv
import io
from datetime import date
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ...sdk.errors import ModuleError
from ...sdk.types import (
    Attribution,
    Episode,
    ExportWarning,
    MediaKind,
    MetadataSearchResult,
    ModuleManifest,
    NormalizedMetadata,
    Provenance,
    RetentionAction,
    RetentionActionKind,
    RetentionPolicy,
    Season,
)


class ManualImportError(ModuleError):
    """A safe Manual metadata validation failure."""

    def __init__(self, message: str) -> None:
        super().__init__(code="manual_import_invalid", message=message)


class ManualConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EpisodeDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    number: int = Field(ge=1)
    title: str
    plot: str | None = None
    air_date: date | None = None
    runtime_minutes: int | None = Field(default=None, ge=0)
    provider_ids: dict[str, str] = Field(default_factory=dict)
    ordering: int | None = None


class SeasonDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    number: int = Field(ge=0)
    title: str | None = None
    plot: str | None = None
    provider_ids: dict[str, str] = Field(default_factory=dict)
    episodes: list[EpisodeDocument] = Field(default_factory=list)


class ManualDocumentV1(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1"]
    external_id: str | None = None
    kind: MediaKind
    locale: str
    titles: dict[str, str]
    original_title: str | None = None
    year: int | None = Field(default=None, ge=1800, le=3000)
    plot: str | None = None
    release_date: date | None = None
    runtime_minutes: int | None = Field(default=None, ge=0)
    provider_ids: dict[str, str] = Field(default_factory=dict)
    ratings: list[dict[str, Any]] = Field(default_factory=list)
    genres: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    studios: list[str] = Field(default_factory=list)
    people: list[dict[str, Any]] = Field(default_factory=list)
    artwork: list[dict[str, Any]] = Field(default_factory=list)
    seasons: list[SeasonDocument] = Field(default_factory=list)

    @field_validator("external_id")
    @classmethod
    def validate_external_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = UUID(value)
        if parsed.version != 4:
            raise ValueError("external_id must be a UUIDv4")
        return str(parsed)


class ManualProvider:
    manifest = ModuleManifest(
        key="manual",
        version="1.0.0",
        contract_version="1",
        name_key="module.manual.name",
        capabilities=frozenset({"movie", "series", "json_import", "episode_csv_import"}),
        translation_keys={"module.manual.name": "Manual"},
    )
    config_model = ManualConfig

    def validate_config(self) -> None:
        ManualConfig()

    def search(self, query: str, locale: str) -> list[MetadataSearchResult]:
        return []

    def fetch(self, kind: str, external_id: str, locale: str) -> dict[str, Any]:
        raise ManualImportError("Manual metadata is read from immutable catalog revisions")

    def normalize(
        self, payload: dict[str, Any], kind: str, external_id: str, locale: str
    ) -> NormalizedMetadata:
        try:
            document = ManualDocumentV1.model_validate(payload)
        except ValidationError as error:
            raise ManualImportError("Manual JSON document is invalid") from error
        if document.kind.value != kind or document.locale != locale:
            raise ManualImportError("Manual normalization identity does not match its document")
        return self._normalize(document, external_id)

    def validate_import_identity(
        self, payload: dict[str, Any]
    ) -> tuple[str | None, MediaKind, str]:
        try:
            document = ManualDocumentV1.model_validate(payload)
        except (ValidationError, ValueError, TypeError) as error:
            raise ManualImportError("Manual JSON document is invalid") from error
        return document.external_id, document.kind, document.locale

    def merge_episode_csv(self, current: NormalizedMetadata, content: str) -> NormalizedMetadata:
        try:
            rows = list(csv.DictReader(io.StringIO(content)))
            required = {"season", "episode", "title"}
            if not rows or not required.issubset(rows[0]):
                raise ManualImportError("episode CSV requires season, episode, and title columns")
            additions: dict[int, list[Episode]] = {}
            for row in rows:
                season_number = int(row["season"])
                episode_number = int(row["episode"])
                if season_number < 0 or episode_number < 1:
                    raise ValueError("invalid episode coordinates")
                episode = Episode(
                    number=episode_number,
                    title=row["title"].strip(),
                    plot=row.get("plot") or None,
                    air_date=date.fromisoformat(row["air_date"]) if row.get("air_date") else None,
                )
                additions.setdefault(season_number, []).append(episode)
            seasons = {season.number: season for season in current.seasons}
            for number, episodes in additions.items():
                prior = seasons.get(number, Season(number=number))
                seasons[number] = prior.model_copy(
                    update={"episodes": prior.episodes + tuple(episodes)}
                )
            return current.model_copy(
                update={"seasons": tuple(seasons[key] for key in sorted(seasons))}
            )
        except (ValidationError, ValueError, TypeError, KeyError, csv.Error) as error:
            raise ManualImportError("episode CSV is invalid; no revision was created") from error

    def attribution(self) -> Attribution:
        return Attribution(provider_key="manual", notice="User-provided metadata")

    def retention_for(self, created_at: Any) -> RetentionPolicy:
        return RetentionPolicy()

    def plan_retention(self, policy: RetentionPolicy, now: Any) -> RetentionAction:
        return RetentionAction(kind=RetentionActionKind.NONE)

    def export_warning(self, policy: RetentionPolicy, now: Any) -> ExportWarning | None:
        del policy, now
        return None

    @staticmethod
    def _normalize(document: ManualDocumentV1, external_id: str) -> NormalizedMetadata:
        data = document.model_dump(exclude={"external_id", "locale"})
        data["seasons"] = [season.model_dump() for season in document.seasons]
        data["provenance"] = Provenance(
            provider_key="manual",
            external_id=external_id,
            locale=document.locale,
            source_label="manual",
        )
        data["completeness"] = 1.0 if document.plot else 0.7
        data["structural_quality"] = 1.0
        return NormalizedMetadata.model_validate(data)


__all__ = ["ManualImportError", "ManualProvider"]
