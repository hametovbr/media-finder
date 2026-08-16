"""Immutable capability DTOs shared by modules and the host."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from math import isfinite
from types import MappingProxyType
from typing import Annotated, Literal, Self

from pydantic import Field, HttpUrl, field_serializer, field_validator, model_validator

from .common import PublicModel
from .errors import JsonValue

MAX_PRIVATE_SELECTION_BYTES = 64 * 1024
MAX_TORRENT_ARTIFACT_BYTES = 20 * 1024 * 1024
MAX_METADATA_IMPORT_BYTES = 1024 * 1024
MAX_EPISODE_TABLE_BYTES = 1024 * 1024
MAX_PROVIDER_PAYLOAD_BYTES = 2 * 1024 * 1024
MAX_PROVIDER_PAYLOAD_DEPTH = 32
MAX_PROVIDER_PAYLOAD_NODES = 100_000


def _freeze_json(
    value: object,
    *,
    depth: int = 0,
    budget: list[int] | None = None,
) -> JsonValue:
    if depth > MAX_PROVIDER_PAYLOAD_DEPTH:
        raise ValueError("provider_payload_too_deep")
    if budget is None:
        budget = [0, 0]
    budget[0] += 1
    if budget[0] > MAX_PROVIDER_PAYLOAD_NODES:
        raise ValueError("provider_payload_too_large")
    if isinstance(value, float) and not isfinite(value):
        raise ValueError("provider_payload_not_json")
    if isinstance(value, str):
        _charge_json(value, budget)
        return value
    if value is None or isinstance(value, int | float | bool):
        _charge_json(value, budget)
        return value
    if isinstance(value, Mapping):
        budget[1] += 2 + max(0, len(value) - 1) + len(value)
        frozen: dict[str, JsonValue] = {}
        for key, item in value.items():
            text_key = str(key)
            _charge_json(text_key, budget)
            frozen[text_key] = _freeze_json(item, depth=depth + 1, budget=budget)
        _require_json_budget(budget)
        return MappingProxyType(frozen)
    if isinstance(value, list | tuple):
        budget[1] += 2 + max(0, len(value) - 1)
        _require_json_budget(budget)
        return tuple(_freeze_json(item, depth=depth + 1, budget=budget) for item in value)
    raise ValueError("provider_payload_not_json")


def _charge_json(value: JsonValue, budget: list[int]) -> None:
    try:
        budget[1] += len(
            json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        )
    except (TypeError, ValueError):
        raise ValueError("provider_payload_not_json") from None
    _require_json_budget(budget)


def _require_json_budget(budget: list[int]) -> None:
    if budget[1] > MAX_PROVIDER_PAYLOAD_BYTES:
        raise ValueError("provider_payload_too_large")


def _thaw_json(value: JsonValue) -> JsonValue:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_thaw_json(item) for item in value)
    return value


def _freeze_string_mapping(value: Mapping[str, str]) -> Mapping[str, str]:
    return MappingProxyType(dict(value))


class MediaKind(StrEnum):
    MOVIE = "movie"
    SERIES = "series"


class MetadataIdentity(PublicModel):
    provider_id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")]
    external_id: Annotated[str, Field(min_length=1, max_length=512)]
    media_kind: MediaKind
    locale: Annotated[str, Field(pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")]


class MetadataSearchQuery(PublicModel):
    query: Annotated[str, Field(min_length=1, max_length=500)]
    locale: Annotated[str, Field(pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")]
    media_kinds: tuple[MediaKind, ...] = (MediaKind.MOVIE, MediaKind.SERIES)
    limit: int = Field(default=50, ge=1, le=100)


class MetadataSearchResult(PublicModel):
    provider_id: str
    external_id: Annotated[str, Field(min_length=1, max_length=512)]
    media_kind: MediaKind
    title: Annotated[str, Field(min_length=1, max_length=1000)]
    year: int | None = Field(default=None, ge=1800, le=3000)
    locale: str


class ProviderPayload(PublicModel):
    """Provider-private JSON payload crossing only the module/core boundary."""

    data: Mapping[str, JsonValue] = Field(
        json_schema_extra={
            "x-media-finder-max-canonical-json-bytes": MAX_PROVIDER_PAYLOAD_BYTES,
            "x-media-finder-max-depth": MAX_PROVIDER_PAYLOAD_DEPTH,
            "x-media-finder-max-nodes": MAX_PROVIDER_PAYLOAD_NODES,
        }
    )

    @field_validator("data", mode="before")
    @classmethod
    def validate_json_payload(cls, value: object) -> object:
        frozen = _freeze_json(value)
        if not isinstance(frozen, Mapping):
            raise ValueError("provider_payload_object_required")
        return frozen

    @field_validator("data")
    @classmethod
    def freeze_payload(cls, value: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
        return MappingProxyType(dict(value))

    @field_serializer("data")
    def serialize_data(self, value: Mapping[str, JsonValue]) -> JsonValue:
        return _thaw_json(value)


class Provenance(PublicModel):
    provider_id: str
    external_id: str
    locale: str
    fetched_at: datetime | None = None
    source_label: str | None = None


class Rating(PublicModel):
    source: str
    value: float
    votes: int | None = Field(default=None, ge=0)


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
    provider_ids: Mapping[str, str] = Field(default_factory=dict)
    ordering: int | None = None

    @field_validator("provider_ids")
    @classmethod
    def freeze_provider_ids(cls, value: Mapping[str, str]) -> Mapping[str, str]:
        return _freeze_string_mapping(value)

    @field_serializer("provider_ids")
    def serialize_provider_ids(self, value: Mapping[str, str]) -> dict[str, str]:
        return dict(value)


class Season(PublicModel):
    number: Annotated[int, Field(ge=0)]
    title: str | None = None
    plot: str | None = None
    episodes: tuple[Episode, ...] = ()
    provider_ids: Mapping[str, str] = Field(default_factory=dict)

    @field_validator("provider_ids")
    @classmethod
    def freeze_provider_ids(cls, value: Mapping[str, str]) -> Mapping[str, str]:
        return _freeze_string_mapping(value)

    @field_serializer("provider_ids")
    def serialize_provider_ids(self, value: Mapping[str, str]) -> dict[str, str]:
        return dict(value)


class NormalizedMetadata(PublicModel):
    schema_version: Literal["1"] = "1"
    kind: MediaKind
    titles: Mapping[str, str]
    original_title: str | None = None
    year: int | None = Field(default=None, ge=1800, le=3000)
    plot: str | None = None
    release_date: date | None = None
    runtime_minutes: int | None = Field(default=None, ge=0)
    provider_ids: Mapping[str, str] = Field(default_factory=dict)
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
    def freeze_titles(cls, value: Mapping[str, str]) -> Mapping[str, str]:
        if not value or any(not title.strip() for title in value.values()):
            raise ValueError("metadata_title_required")
        return _freeze_string_mapping(value)

    @field_validator("provider_ids")
    @classmethod
    def freeze_provider_ids(cls, value: Mapping[str, str]) -> Mapping[str, str]:
        return _freeze_string_mapping(value)

    @field_serializer("titles", "provider_ids")
    def serialize_string_mapping(self, value: Mapping[str, str]) -> dict[str, str]:
        return dict(value)


@dataclass(frozen=True, slots=True, repr=False)
class MetadataImportDocument:
    """Bounded provider-owned structured metadata input."""

    _content: bytes

    @classmethod
    def from_bytes(cls, content: bytes) -> MetadataImportDocument:
        copied = bytes(content)
        if not copied or len(copied) > MAX_METADATA_IMPORT_BYTES:
            raise ValueError("metadata_import_document_too_large")
        return cls(copied)

    def content(self) -> bytes:
        return self._content

    def __repr__(self) -> str:
        return f"MetadataImportDocument(<redacted>, bytes={len(self._content)})"


@dataclass(frozen=True, slots=True, repr=False)
class EpisodeTableDocument:
    """Bounded provider-owned episode table input."""

    _content: bytes

    @classmethod
    def from_bytes(cls, content: bytes) -> EpisodeTableDocument:
        copied = bytes(content)
        if not copied or len(copied) > MAX_EPISODE_TABLE_BYTES:
            raise ValueError("episode_table_document_too_large")
        return cls(copied)

    def content(self) -> bytes:
        return self._content

    def __repr__(self) -> str:
        return f"EpisodeTableDocument(<redacted>, bytes={len(self._content)})"


class MetadataEditResult(PublicModel):
    """Validated provider identity, raw envelope, and normalized edit result."""

    identity: MetadataIdentity
    raw_payload: ProviderPayload
    metadata: NormalizedMetadata

    @model_validator(mode="after")
    def require_consistent_identity(self) -> Self:
        provenance = self.metadata.provenance
        if (
            self.identity.media_kind is not self.metadata.kind
            or self.identity.provider_id != provenance.provider_id
            or self.identity.external_id != provenance.external_id
            or self.identity.locale != provenance.locale
        ):
            raise ValueError("metadata_edit_identity_mismatch")
        return self


class RetentionPolicy(PublicModel):
    refresh_after: datetime | None = None
    expires_at: datetime | None = None


class RetentionSubject(PublicModel):
    identity: MetadataIdentity
    policy: RetentionPolicy


class RetentionActionKind(StrEnum):
    NONE = "none"
    REFRESH = "refresh"
    PURGE = "purge"


class RetentionAction(PublicModel):
    kind: RetentionActionKind
    mandatory: bool = False


class ExportHeader(PublicModel):
    name: Literal["Warning", "Sunset", "X-Media-Finder-Metadata-Expires"]
    value: Annotated[str, Field(min_length=1, max_length=512)]

    @field_validator("value")
    @classmethod
    def reject_header_injection(cls, value: str) -> str:
        if "\r" in value or "\n" in value:
            raise ValueError("export_warning_header_unsafe")
        return value


class ExportWarning(PublicModel):
    headers: tuple[ExportHeader, ...]

    @field_validator("headers")
    @classmethod
    def require_unique_headers(cls, value: tuple[ExportHeader, ...]) -> tuple[ExportHeader, ...]:
        names = tuple(header.name for header in value)
        if not names or len(names) != len(set(names)):
            raise ValueError("export_warning_headers_invalid")
        return value


class ReleaseSearchFilter(PublicModel):
    key: Annotated[str, Field(pattern=r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")]
    values: tuple[Annotated[str, Field(min_length=1, max_length=200)], ...]


class ReleaseSearchQuery(PublicModel):
    query: Annotated[str, Field(min_length=1, max_length=500)]
    filters: tuple[ReleaseSearchFilter, ...] = ()
    limit: int = Field(default=50, ge=1, le=100)


class SafeReleaseSnapshot(PublicModel):
    title: Annotated[str, Field(min_length=1, max_length=1000)]
    indexer: Annotated[str, Field(min_length=1, max_length=300)]
    guid: Annotated[str, Field(min_length=1, max_length=512)] | None = None
    infohash: Annotated[str, Field(pattern=r"^(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})$")] | None = None
    source_page_url: HttpUrl | None = None


@dataclass(frozen=True, slots=True, repr=False)
class PrivateReleaseSelection:
    _payload: bytes

    @classmethod
    def from_bytes(cls, payload: bytes) -> PrivateReleaseSelection:
        copied = bytes(payload)
        if not copied or len(copied) > MAX_PRIVATE_SELECTION_BYTES:
            raise ValueError("release_selection_too_large")
        return cls(copied)

    def payload(self) -> bytes:
        return self._payload

    def __repr__(self) -> str:
        return f"PrivateReleaseSelection(<redacted>, bytes={len(self._payload)})"


@dataclass(frozen=True, slots=True)
class ReleaseCandidate:
    snapshot: SafeReleaseSnapshot
    selection: PrivateReleaseSelection


class MagnetArtifact(PublicModel):
    kind: Literal["magnet"] = "magnet"
    uri: Annotated[str, Field(pattern=r"^magnet:\?", max_length=8192)]


@dataclass(frozen=True, slots=True, repr=False)
class TorrentArtifact:
    _content: bytes
    kind: Literal["torrent"] = "torrent"

    @classmethod
    def from_bytes(cls, content: bytes) -> TorrentArtifact:
        copied = bytes(content)
        if not copied or len(copied) > MAX_TORRENT_ARTIFACT_BYTES:
            raise ValueError("torrent_artifact_too_large")
        return cls(copied)

    def content(self) -> bytes:
        return self._content

    def __repr__(self) -> str:
        return f"TorrentArtifact(<redacted>, bytes={len(self._content)})"


type DownloadArtifact = MagnetArtifact | TorrentArtifact


class DownloadDestination(PublicModel):
    key: Annotated[str, Field(min_length=1, max_length=500)]
    label: Annotated[str, Field(min_length=1, max_length=500)]


class SubmissionResult(PublicModel):
    accepted: bool
    external_task_id: str | None = None
    correlation: Annotated[str, Field(min_length=1, max_length=200)]


class CorrelationResult(PublicModel):
    found: bool
    correlation: Annotated[str, Field(min_length=1, max_length=200)]
    external_task_id: str | None = None
    conclusive: bool = True


__all__ = [
    "MAX_EPISODE_TABLE_BYTES",
    "MAX_METADATA_IMPORT_BYTES",
    "MAX_PRIVATE_SELECTION_BYTES",
    "MAX_PROVIDER_PAYLOAD_BYTES",
    "MAX_PROVIDER_PAYLOAD_DEPTH",
    "MAX_PROVIDER_PAYLOAD_NODES",
    "MAX_TORRENT_ARTIFACT_BYTES",
    "Artwork",
    "CorrelationResult",
    "DownloadArtifact",
    "DownloadDestination",
    "Episode",
    "EpisodeTableDocument",
    "ExportHeader",
    "ExportWarning",
    "MagnetArtifact",
    "MediaKind",
    "MetadataEditResult",
    "MetadataIdentity",
    "MetadataImportDocument",
    "MetadataSearchQuery",
    "MetadataSearchResult",
    "NormalizedMetadata",
    "Person",
    "PrivateReleaseSelection",
    "Provenance",
    "ProviderPayload",
    "Rating",
    "ReleaseCandidate",
    "ReleaseSearchFilter",
    "ReleaseSearchQuery",
    "RetentionAction",
    "RetentionActionKind",
    "RetentionPolicy",
    "RetentionSubject",
    "SafeReleaseSnapshot",
    "Season",
    "SubmissionResult",
    "TorrentArtifact",
]
