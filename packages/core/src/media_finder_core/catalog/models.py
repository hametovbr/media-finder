"""Immutable values crossing the catalog application boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from media_finder_sdk import MediaKind, NormalizedMetadata, ProviderPayload
from media_finder_sdk.errors import JsonValue


@dataclass(frozen=True, slots=True)
class CatalogIdentity:
    provider_id: str
    external_id: str
    media_kind: MediaKind


@dataclass(frozen=True, slots=True)
class CollectionSnapshot:
    id: str
    name: str
    archived_at: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class MediaItemSnapshot:
    id: str
    identity: CatalogIdentity
    collection_id: str | None
    normalized_title: str | None
    year: int | None
    current_revision_id: str | None
    archived_at: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class RevisionDraft:
    raw_payload: ProviderPayload | None
    normalized: NormalizedMetadata
    overrides: Mapping[str, JsonValue]
    effective: NormalizedMetadata
    refresh_after: datetime | None
    expires_at: datetime | None
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "overrides", _freeze_mapping(self.overrides))


@dataclass(frozen=True, slots=True)
class MetadataRevisionSnapshot:
    id: str
    media_item_id: str
    revision_number: int
    identity: CatalogIdentity
    locale: str
    schema_version: str
    raw_payload: ProviderPayload | None
    normalized: NormalizedMetadata | None
    overrides: Mapping[str, JsonValue]
    effective: NormalizedMetadata | None
    refresh_after: datetime | None
    expires_at: datetime | None
    created_at: datetime
    expired_at: datetime | None = None
    maintenance_status: str | None = None
    maintenance_error_code: str | None = None
    maintenance_attempted_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "overrides", _freeze_mapping(self.overrides))


def _freeze_json(value: JsonValue) -> JsonValue:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze_json(item) for item in value)
    return value


def _freeze_mapping(value: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
    return MappingProxyType({str(key): _freeze_json(item) for key, item in value.items()})


@dataclass(frozen=True, slots=True)
class ItemResolution:
    item: MediaItemSnapshot
    created: bool


@dataclass(frozen=True, slots=True)
class CatalogPage[T]:
    items: tuple[T, ...]
    next_after: tuple[str, str] | None


__all__ = [
    "CatalogIdentity",
    "CatalogPage",
    "CollectionSnapshot",
    "ItemResolution",
    "MediaItemSnapshot",
    "MetadataRevisionSnapshot",
    "RevisionDraft",
]
