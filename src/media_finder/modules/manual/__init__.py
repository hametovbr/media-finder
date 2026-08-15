"""Durable Manual metadata provider and atomic import operations."""

import csv
from datetime import date
from typing import Any, Literal, TextIO
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ...domain import CatalogService, RevisionInput
from ...models import MediaItem
from ...sdk.types import (
    Attribution,
    Episode,
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


class ManualImportError(ValueError):
    """A safe, atomic Manual import validation failure."""


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

    def __init__(self, catalog: CatalogService) -> None:
        self.catalog = catalog

    def validate_config(self) -> None:
        ManualConfig()

    def search(self, query: str, locale: str) -> list[MetadataSearchResult]:
        return []

    def fetch(self, kind: str, external_id: str, locale: str) -> NormalizedMetadata:
        raise ManualImportError("Manual metadata is read from immutable catalog revisions")

    def normalize(
        self, payload: dict[str, Any], kind: str, external_id: str, locale: str
    ) -> NormalizedMetadata:
        try:
            document = ManualDocumentV1.model_validate(payload)
        except ValidationError as error:
            raise ManualImportError("Manual JSON document is invalid") from error
        return self._normalize(document, external_id)

    def attribution(self) -> Attribution:
        return Attribution(provider_key="manual", notice="User-provided metadata")

    def retention_for(self, created_at: Any) -> RetentionPolicy:
        return RetentionPolicy()

    def plan_retention(self, policy: RetentionPolicy, now: Any) -> RetentionAction:
        return RetentionAction(kind=RetentionActionKind.NONE)

    def import_json(self, payload: dict[str, Any], *, confirm_existing: bool = False) -> MediaItem:
        try:
            document = ManualDocumentV1.model_validate(payload)
            identity = document.external_id
            normalized = self._normalize(document, identity or "pending")
        except (ValidationError, ValueError, TypeError) as error:
            self.catalog.session.rollback()
            raise ManualImportError("Manual JSON document is invalid") from error

        if identity is not None:
            existing, created = self.catalog.get_or_create_item("manual", identity, document.kind)
            if not created:
                if confirm_existing:
                    normalized = normalized.model_copy(
                        update={
                            "provenance": normalized.provenance.model_copy(
                                update={"external_id": identity}
                            )
                        }
                    )
                    self.catalog.add_revision(existing, RevisionInput.from_normalized(normalized))
                return existing
            normalized = normalized.model_copy(
                update={
                    "provenance": normalized.provenance.model_copy(update={"external_id": identity})
                }
            )
            self.catalog.add_revision(existing, RevisionInput.from_normalized(normalized))
            return existing
        return self.catalog.create_manual_item(normalized)

    def import_episode_csv(self, media_item_id: str, source: TextIO) -> MediaItem:
        item = self.catalog.session.get(MediaItem, media_item_id)
        if item is None or item.provider_key != "manual" or item.kind != "series":
            raise ManualImportError("episode CSV target must be a Manual series")
        current = item.current_revision
        if current is None or current.effective_payload is None:
            raise ManualImportError("Manual series has no current metadata")
        try:
            rows = list(csv.DictReader(source))
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
                    plot=(row.get("plot") or None),
                    air_date=(date.fromisoformat(row["air_date"]) if row.get("air_date") else None),
                )
                additions.setdefault(season_number, []).append(episode)
            normalized = NormalizedMetadata.model_validate(current.effective_payload)
            seasons = {season.number: season for season in normalized.seasons}
            for number, episodes in additions.items():
                prior = seasons.get(number, Season(number=number))
                seasons[number] = prior.model_copy(
                    update={"episodes": prior.episodes + tuple(episodes)}
                )
            normalized = normalized.model_copy(
                update={"seasons": tuple(seasons[key] for key in sorted(seasons))}
            )
        except (ValidationError, ValueError, TypeError, KeyError, csv.Error) as error:
            self.catalog.session.rollback()
            raise ManualImportError("episode CSV is invalid; no revision was created") from error
        self.catalog.add_revision(item, RevisionInput.from_normalized(normalized))
        return item

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
