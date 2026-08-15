"""Manual JSON document validation and normalization."""

from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from media_finder_sdk import (
    Artwork,
    Episode,
    MediaKind,
    MetadataIdentity,
    NormalizedMetadata,
    Person,
    Provenance,
    Rating,
    Season,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator


class EpisodeDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: int = Field(ge=1)
    title: str
    plot: str | None = None
    air_date: date | None = None
    runtime_minutes: int | None = Field(default=None, ge=0)
    provider_ids: dict[str, str] = Field(default_factory=dict)
    ordering: int | None = None

    def normalized(self) -> Episode:
        return Episode.model_validate(self.model_dump())


class SeasonDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: int = Field(ge=0)
    title: str | None = None
    plot: str | None = None
    provider_ids: dict[str, str] = Field(default_factory=dict)
    episodes: tuple[EpisodeDocument, ...] = ()

    def normalized(self) -> Season:
        return Season(
            number=self.number,
            title=self.title,
            plot=self.plot,
            provider_ids=self.provider_ids,
            episodes=tuple(episode.normalized() for episode in self.episodes),
        )


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
    ratings: tuple[Rating, ...] = ()
    genres: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    countries: tuple[str, ...] = ()
    studios: tuple[str, ...] = ()
    people: tuple[Person, ...] = ()
    artwork: tuple[Artwork, ...] = ()
    seasons: tuple[SeasonDocument, ...] = ()

    @field_validator("external_id")
    @classmethod
    def validate_external_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = UUID(value)
        if parsed.version != 4:
            raise ValueError("manual_external_id_invalid")
        return str(parsed)

    def normalized(self, identity: MetadataIdentity) -> NormalizedMetadata:
        if (
            identity.provider_id != "manual"
            or identity.media_kind is not self.kind
            or identity.locale != self.locale
            or (self.external_id is not None and self.external_id != identity.external_id)
        ):
            raise ValueError("manual_identity_mismatch")
        return NormalizedMetadata(
            kind=self.kind,
            titles=self.titles,
            original_title=self.original_title,
            year=self.year,
            plot=self.plot,
            release_date=self.release_date,
            runtime_minutes=self.runtime_minutes,
            provider_ids=self.provider_ids,
            ratings=self.ratings,
            genres=self.genres,
            tags=self.tags,
            countries=self.countries,
            studios=self.studios,
            people=self.people,
            artwork=self.artwork,
            seasons=tuple(season.normalized() for season in self.seasons),
            provenance=Provenance(
                provider_id="manual",
                external_id=identity.external_id,
                locale=self.locale,
                source_label="manual",
            ),
            completeness=1.0 if self.plot else 0.7,
            structural_quality=1.0,
        )


__all__: list[str] = []
