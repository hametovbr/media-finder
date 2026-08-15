"""Canonical version-one module and normalized metadata types."""

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class PublicModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class MediaKind(StrEnum):
    MOVIE = "movie"
    SERIES = "series"


class ModuleKind(StrEnum):
    METADATA_PROVIDER = "metadata_provider"
    DOWNLOAD_CLIENT = "download_client"


class ModuleManifest(PublicModel):
    key: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]*$")]
    version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    contract_version: Literal["1"]
    name_key: str
    kind: ModuleKind = ModuleKind.METADATA_PROVIDER
    capabilities: frozenset[str] = frozenset()
    translation_keys: dict[str, str] = Field(default_factory=dict)


class Provenance(PublicModel):
    provider_key: str
    external_id: str
    locale: str
    fetched_at: datetime | None = None
    source_label: str | None = None


class Rating(PublicModel):
    source: str
    value: float
    votes: int | None = None


class Person(PublicModel):
    name: str
    role: str
    character: str | None = None


class Artwork(PublicModel):
    kind: str
    url: HttpUrl
    language: str | None = None


class Episode(PublicModel):
    number: Annotated[int, Field(ge=1)]
    title: str
    plot: str | None = None
    air_date: date | None = None
    runtime_minutes: int | None = Field(default=None, ge=0)
    provider_ids: dict[str, str] = Field(default_factory=dict)
    ordering: int | None = None


class Season(PublicModel):
    number: Annotated[int, Field(ge=0)]
    title: str | None = None
    plot: str | None = None
    episodes: tuple[Episode, ...] = ()
    provider_ids: dict[str, str] = Field(default_factory=dict)


class NormalizedMetadata(PublicModel):
    schema_version: Literal["1"] = "1"
    kind: MediaKind
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
    seasons: tuple[Season, ...] = ()
    provenance: Provenance
    completeness: float = Field(default=0.0, ge=0, le=1)
    structural_quality: float = Field(default=0.0, ge=0, le=1)

    @field_validator("titles")
    @classmethod
    def require_title(cls, value: dict[str, str]) -> dict[str, str]:
        if not value or any(not title.strip() for title in value.values()):
            raise ValueError("at least one non-empty localized title is required")
        return value


class MetadataSearchResult(PublicModel):
    provider_key: str
    external_id: str
    kind: MediaKind
    title: str
    year: int | None = None
    locale: str


class Attribution(PublicModel):
    provider_key: str
    notice: str
    url: HttpUrl | None = None


class RetentionPolicy(PublicModel):
    refresh_after: datetime | None = None
    expires_at: datetime | None = None


class ExportWarning(PublicModel):
    """Provider-supplied, allowlisted warning headers for an export."""

    headers: dict[str, str]

    @field_validator("headers")
    @classmethod
    def safe_headers(cls, value: dict[str, str]) -> dict[str, str]:
        allowed = {"Warning", "Sunset", "X-Media-Finder-Metadata-Expires"}
        if not value or set(value) - allowed:
            raise ValueError("export warning contains an unsupported header")
        if any("\r" in item or "\n" in item or len(item) > 512 for item in value.values()):
            raise ValueError("export warning contains an unsafe header value")
        return value


class RetentionActionKind(StrEnum):
    NONE = "none"
    REFRESH = "refresh"
    PURGE = "purge"


class RetentionAction(PublicModel):
    kind: RetentionActionKind
    mandatory: bool = False


class RetentionSubject(PublicModel):
    provider_key: str
    external_id: str
    media_kind: MediaKind
    locale: str
    policy: RetentionPolicy


class RetentionExecutionStatus(StrEnum):
    NOOP = "noop"
    REFRESHED = "refreshed"
    FAILED = "failed"
    PURGED = "purged"


class RetentionExecution(PublicModel):
    status: RetentionExecutionStatus
    error_code: str | None = None


class MagnetArtifact(PublicModel):
    kind: Literal["magnet"] = "magnet"
    uri: str


class TorrentArtifact(PublicModel):
    kind: Literal["torrent"] = "torrent"
    content: bytes


DownloadArtifact = MagnetArtifact | TorrentArtifact


class DownloadDestination(PublicModel):
    key: str
    label: str


class SubmissionResult(PublicModel):
    accepted: bool
    external_task_id: str | None = None
    correlation: str


class CorrelationResult(PublicModel):
    found: bool
    correlation: str
    external_task_id: str | None = None
    conclusive: bool = True


JsonObject = dict[str, Any]
