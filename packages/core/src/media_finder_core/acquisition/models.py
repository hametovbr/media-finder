"""Immutable values owned by the acquisition bounded context."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from media_finder_sdk import (
    DownloadDestination,
    SafeReleaseSnapshot,
    is_safe_public_source_page,
    is_safe_release_guid,
)

_MODULE_ID = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")


class AcquisitionStatus(StrEnum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ModuleVersionSnapshot:
    module_id: str
    module_version: str

    def __post_init__(self) -> None:
        if len(self.module_id) > 100 or _MODULE_ID.fullmatch(self.module_id) is None:
            raise ValueError("module_identity_invalid")
        if re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z.+-]{0,99}", self.module_version) is None:
            raise ValueError("module_version_invalid")


@dataclass(frozen=True, slots=True)
class AcquisitionRequest:
    media_item_id: str
    metadata_revision_id: str
    destination: str
    release_token: str
    idempotency_key: str
    naming_profile: str

    def __post_init__(self) -> None:
        _bounded(self.media_item_id, 100, "acquisition_reference_invalid")
        _bounded(self.metadata_revision_id, 100, "acquisition_reference_invalid")
        _bounded(self.destination, 500, "download_destination_invalid")
        _bounded(self.release_token, 500, "release_search_token_expired")
        _bounded(self.idempotency_key, 200, "acquisition_idempotency_key_invalid")
        _bounded(self.naming_profile, 100, "naming_profile_invalid")


@dataclass(frozen=True, slots=True)
class AcquisitionDraft:
    id: UUID
    media_item_id: str
    metadata_revision_id: str
    idempotency_key: str
    naming_profile: str
    destination: str
    correlation: str
    release_snapshot: SafeReleaseSnapshot
    release_provider: ModuleVersionSnapshot
    download_client: ModuleVersionSnapshot
    created_at: datetime

    def __post_init__(self) -> None:
        if self.correlation != f"mf-acq-{self.id}":
            raise ValueError("download_client_correlation_mismatch")
        object.__setattr__(self, "release_snapshot", safe_release_snapshot(self.release_snapshot))


@dataclass(frozen=True, slots=True)
class AcquisitionSnapshot:
    id: str
    media_item_id: str
    metadata_revision_id: str
    idempotency_key: str
    naming_profile: str
    status: AcquisitionStatus
    destination: str
    correlation: str
    release_snapshot: SafeReleaseSnapshot
    release_provider: ModuleVersionSnapshot
    download_client: ModuleVersionSnapshot
    external_task_id: str | None
    failure_code: str | None
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        try:
            identity = UUID(self.id)
        except ValueError as error:
            raise ValueError("acquisition_identity_invalid") from error
        if self.correlation != f"mf-acq-{identity}":
            raise ValueError("download_client_correlation_mismatch")
        object.__setattr__(self, "release_snapshot", safe_release_snapshot(self.release_snapshot))


@dataclass(frozen=True, slots=True)
class AcquisitionResolution:
    acquisition: AcquisitionSnapshot
    created: bool


class DestinationUnavailable(ValueError):
    def __init__(self, current_destinations: tuple[DownloadDestination, ...]) -> None:
        super().__init__("download_destination_unavailable")
        self.current_destinations = current_destinations


def safe_release_snapshot(value: SafeReleaseSnapshot) -> SafeReleaseSnapshot:
    copied = SafeReleaseSnapshot.model_validate(value.model_dump(mode="json"))
    guid = copied.guid
    if guid is not None and not is_safe_release_guid(guid):
        guid = None
    infohash = copied.infohash.lower() if copied.infohash is not None else None
    source_page_url = copied.source_page_url
    if source_page_url is not None and not is_safe_public_source_page(str(source_page_url)):
        source_page_url = None
    return SafeReleaseSnapshot(
        title=copied.title,
        indexer=copied.indexer,
        guid=guid,
        infohash=infohash,
        source_page_url=source_page_url,
    )


def _bounded(value: str, maximum: int, code: str) -> None:
    if not value or len(value) > maximum or any(ord(character) < 32 for character in value):
        raise ValueError(code)


__all__ = [
    "AcquisitionDraft",
    "AcquisitionRequest",
    "AcquisitionResolution",
    "AcquisitionSnapshot",
    "AcquisitionStatus",
    "DestinationUnavailable",
    "ModuleVersionSnapshot",
    "safe_release_snapshot",
]
