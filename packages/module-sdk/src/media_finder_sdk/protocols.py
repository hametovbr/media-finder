"""Synchronous specialized capability contracts for trusted modules."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from .types import (
    CorrelationResult,
    DownloadArtifact,
    DownloadDestination,
    EpisodeTableDocument,
    ExportWarning,
    MetadataEditResult,
    MetadataIdentity,
    MetadataImportDocument,
    MetadataSearchQuery,
    MetadataSearchResult,
    NormalizedMetadata,
    PrivateReleaseSelection,
    ProviderPayload,
    ReleaseCandidate,
    ReleaseSearchQuery,
    RetentionAction,
    RetentionPolicy,
    RetentionSubject,
    SubmissionResult,
)


@runtime_checkable
class MetadataProvider(Protocol):
    def validate(self) -> None: ...
    def search(self, query: MetadataSearchQuery) -> tuple[MetadataSearchResult, ...]: ...
    def fetch(self, identity: MetadataIdentity) -> ProviderPayload: ...
    def normalize(
        self, payload: ProviderPayload, identity: MetadataIdentity
    ) -> NormalizedMetadata: ...
    def close(self) -> None: ...


@runtime_checkable
class MetadataEditor(Protocol):
    def import_document(self, document: MetadataImportDocument) -> MetadataEditResult: ...
    def merge_episode_table(
        self, current: NormalizedMetadata, document: EpisodeTableDocument
    ) -> MetadataEditResult: ...
    def close(self) -> None: ...


@runtime_checkable
class MetadataRetentionPolicy(Protocol):
    def retention_for(self, created_at: datetime) -> RetentionPolicy: ...
    def plan(self, subject: RetentionSubject, now: datetime) -> RetentionAction: ...
    def export_warning(self, policy: RetentionPolicy, now: datetime) -> ExportWarning | None: ...
    def close(self) -> None: ...


@runtime_checkable
class ReleaseProvider(Protocol):
    def validate(self) -> None: ...
    def search(self, query: ReleaseSearchQuery) -> tuple[ReleaseCandidate, ...]: ...
    def resolve(self, selection: PrivateReleaseSelection) -> DownloadArtifact: ...
    def close(self) -> None: ...


@runtime_checkable
class DownloadClient(Protocol):
    def validate(self) -> None: ...
    def list_destinations(self) -> tuple[DownloadDestination, ...]: ...
    def submit(
        self, artifact: DownloadArtifact, destination: str, correlation: str
    ) -> SubmissionResult: ...
    def find_by_correlation(self, correlation: str) -> CorrelationResult: ...
    def close(self) -> None: ...


__all__ = [
    "DownloadClient",
    "MetadataEditor",
    "MetadataProvider",
    "MetadataRetentionPolicy",
    "ReleaseProvider",
]
