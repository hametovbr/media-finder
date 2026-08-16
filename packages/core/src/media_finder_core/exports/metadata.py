"""Current and pinned normalized-metadata export use cases."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from media_finder_sdk import (
    ExportWarning,
    NormalizedMetadata,
    RetentionPolicy,
)

from .ports import AcquisitionExportReadPort, CatalogExportReadPort


class ExportWarningPolicy(Protocol):
    def export_warning(self, policy: RetentionPolicy, now: datetime) -> ExportWarning | None: ...


@dataclass(frozen=True, slots=True)
class ExportRevisionSnapshot:
    id: str
    effective: NormalizedMetadata | None
    refresh_after: datetime | None
    expires_at: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ResolvedMetadata:
    revision_id: str
    metadata: NormalizedMetadata
    refresh_after: datetime | None
    expires_at: datetime | None
    created_at: datetime


class MetadataExportService:
    def __init__(
        self,
        *,
        catalog: CatalogExportReadPort,
        acquisitions: AcquisitionExportReadPort,
        retention_policies: Mapping[str, ExportWarningPolicy],
        clock: Callable[[], datetime],
    ) -> None:
        self._catalog = catalog
        self._acquisitions = acquisitions
        self._retention_policies = dict(retention_policies)
        self._clock = clock

    def current(self, media_item_id: str) -> ResolvedMetadata:
        revision_id = self._catalog.current_revision_id(media_item_id)
        if revision_id is None:
            raise ValueError("media_item_not_found")
        return self._resolve(revision_id)

    def pinned(self, acquisition_id: str) -> ResolvedMetadata:
        revision_id = self._acquisitions.pinned_revision_id(acquisition_id)
        if revision_id is None:
            raise ValueError("acquisition_not_found")
        return self._resolve(revision_id)

    def warning(self, resolved: ResolvedMetadata) -> ExportWarning | None:
        policy = self._retention_policies.get(resolved.metadata.provenance.provider_id)
        if policy is None:
            return None
        try:
            warning = policy.export_warning(
                RetentionPolicy(
                    refresh_after=resolved.refresh_after,
                    expires_at=resolved.expires_at,
                ),
                _utc(self._clock()),
            )
            if warning is None:
                return None
            return ExportWarning.model_validate(warning.model_dump(mode="json"))
        except Exception:
            raise ValueError("export_warning_invalid") from None

    def _resolve(self, revision_id: str) -> ResolvedMetadata:
        revision = self._catalog.revision(revision_id)
        if revision is None:
            raise ValueError("metadata_revision_not_found")
        now = _utc(self._clock())
        expires_at = _optional_utc(revision.expires_at)
        if revision.effective is None or (expires_at is not None and now >= expires_at):
            raise ValueError("metadata_source_expired")
        try:
            metadata = NormalizedMetadata.model_validate(revision.effective.model_dump(mode="json"))
        except Exception:
            raise ValueError("metadata_snapshot_invalid") from None
        return ResolvedMetadata(
            revision_id=revision.id,
            metadata=metadata,
            refresh_after=_optional_utc(revision.refresh_after),
            expires_at=expires_at,
            created_at=_utc(revision.created_at),
        )


def _optional_utc(value: datetime | None) -> datetime | None:
    return _utc(value) if value is not None else None


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


__all__ = [
    "ExportRevisionSnapshot",
    "ExportWarningPolicy",
    "MetadataExportService",
    "ResolvedMetadata",
]
