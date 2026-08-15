"""Complete Manual metadata schema-v1 browser document."""

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, HttpUrl, field_validator

from .common import ControlModel, Locale, MediaKind


class RatingDocument(ControlModel):
    source: str
    value: float
    votes: int | None = None


class PersonDocument(ControlModel):
    name: str
    role: str
    character: str | None = None


class ArtworkDocument(ControlModel):
    kind: str
    url: HttpUrl
    language: str | None = None


class EpisodeDocument(ControlModel):
    number: Annotated[int, Field(ge=1)]
    title: str
    plot: str | None = None
    air_date: date | None = None
    runtime_minutes: int | None = Field(default=None, ge=0)
    provider_ids: dict[str, str] = Field(default_factory=dict)
    ordering: int | None = None


class SeasonDocument(ControlModel):
    number: Annotated[int, Field(ge=0)]
    title: str | None = None
    plot: str | None = None
    provider_ids: dict[str, str] = Field(default_factory=dict)
    episodes: tuple[EpisodeDocument, ...] = ()


class ManualDocumentV1(ControlModel):
    schema_version: Literal["1"] = "1"
    external_id: str | None = None
    kind: MediaKind
    locale: Locale
    titles: dict[str, str]
    original_title: str | None = None
    year: int | None = Field(default=None, ge=1800, le=3000)
    plot: str | None = None
    release_date: date | None = None
    runtime_minutes: int | None = Field(default=None, ge=0)
    provider_ids: dict[str, str] = Field(default_factory=dict)
    ratings: tuple[RatingDocument, ...] = ()
    genres: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    countries: tuple[str, ...] = ()
    studios: tuple[str, ...] = ()
    people: tuple[PersonDocument, ...] = ()
    artwork: tuple[ArtworkDocument, ...] = ()
    seasons: tuple[SeasonDocument, ...] = ()

    @field_validator("external_id")
    @classmethod
    def canonical_uuid4(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = UUID(value)
        if parsed.version != 4:
            raise ValueError("external_id must be a UUIDv4")
        return str(parsed)

    @field_validator("titles")
    @classmethod
    def require_title(cls, value: dict[str, str]) -> dict[str, str]:
        if not value or any(not title.strip() for title in value.values()):
            raise ValueError("at least one non-empty localized title is required")
        return value
