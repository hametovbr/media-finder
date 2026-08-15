"""Structural module protocols; modules never receive application internals."""

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from ._retention import InternalRetentionResult
from .types import (
    Attribution,
    CorrelationResult,
    DownloadArtifact,
    DownloadDestination,
    MetadataSearchResult,
    ModuleManifest,
    NormalizedMetadata,
    RetentionAction,
    RetentionPolicy,
    RetentionSubject,
    SubmissionResult,
)


@runtime_checkable
class MetadataProvider(Protocol):
    manifest: ModuleManifest
    config_model: type[BaseModel]

    def validate_config(self) -> None: ...
    def search(self, query: str, locale: str) -> list[MetadataSearchResult]: ...
    def fetch(self, kind: str, external_id: str, locale: str) -> dict[str, Any]: ...
    def normalize(
        self, payload: dict[str, Any], kind: str, external_id: str, locale: str
    ) -> NormalizedMetadata: ...
    def attribution(self) -> Attribution: ...
    def retention_for(self, created_at: datetime) -> RetentionPolicy: ...
    def plan_retention(self, policy: RetentionPolicy, now: datetime) -> RetentionAction: ...
    def execute_retention(
        self, subject: RetentionSubject, action: RetentionAction, now: datetime
    ) -> InternalRetentionResult: ...


@runtime_checkable
class DownloadClient(Protocol):
    manifest: ModuleManifest
    config_model: type[BaseModel]

    def validate_config(self) -> None: ...
    def list_destinations(self) -> list[DownloadDestination]: ...
    def submit(
        self, artifact: DownloadArtifact, destination: str, correlation: str
    ) -> SubmissionResult: ...
    def find_by_correlation(self, correlation: str) -> CorrelationResult: ...


class JsonTransport(Protocol):
    def get_json(self, path: str, params: dict[str, str]) -> dict[str, Any]: ...
