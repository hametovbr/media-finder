"""Capability-specific conformance fixtures and executable assertions."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .environment import resolve_module_environment
from .errors import ModuleError
from .registration import (
    DownloadClientRegistration,
    MetadataProviderRegistration,
    ReleaseProviderRegistration,
    StaticModuleRegistry,
)
from .types import (
    CorrelationResult,
    DownloadArtifact,
    DownloadDestination,
    ExportWarning,
    MagnetArtifact,
    MetadataIdentity,
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
    TorrentArtifact,
)


@dataclass(frozen=True, slots=True)
class MetadataConformanceFixture:
    environment: Mapping[str, str]
    query: MetadataSearchQuery
    expected_results: tuple[MetadataSearchResult, ...]
    identity: MetadataIdentity
    expected_payload: ProviderPayload
    expected_metadata: NormalizedMetadata
    invalid_identity: MetadataIdentity
    expected_error_code: str
    created_at: datetime
    now: datetime
    expected_policy: RetentionPolicy
    expected_action: RetentionAction
    expected_warning: ExportWarning | None


@dataclass(frozen=True, slots=True)
class ReleaseConformanceFixture:
    environment: Mapping[str, str]
    query: ReleaseSearchQuery
    expected_candidates: tuple[ReleaseCandidate, ...]
    expected_artifact: DownloadArtifact
    invalid_selection: PrivateReleaseSelection
    expected_error_code: str


@dataclass(frozen=True, slots=True)
class DownloadClientConformanceFixture:
    environment: Mapping[str, str]
    expected_destinations: tuple[DownloadDestination, ...]
    artifacts: tuple[DownloadArtifact, ...]
    destination: str
    invalid_destination: str
    correlation: str
    expected_submission: SubmissionResult
    expected_correlation: CorrelationResult
    expected_error_code: str


def _assert_module_error(operation: Callable[[], object], expected_code: str) -> None:
    try:
        operation()
    except ModuleError as error:
        if error.code != expected_code:
            raise AssertionError((error.code, expected_code)) from error
    else:
        raise AssertionError("module_standardized_error_not_raised")


class _Closeable(Protocol):
    def close(self) -> None: ...


def _close_twice(instance: _Closeable) -> None:
    close = instance.close
    close()
    close()


def assert_metadata_registration_conforms(
    registration: MetadataProviderRegistration,
    fixture: MetadataConformanceFixture,
) -> None:
    StaticModuleRegistry.create(metadata=(registration,))
    environment = resolve_module_environment(registration.manifest, fixture.environment)
    provider = registration.build(environment)
    try:
        provider.validate()
        results = provider.search(fixture.query)
        if results != fixture.expected_results or len(results) > fixture.query.limit:
            raise AssertionError("metadata_search_result_mismatch")
        payload = provider.fetch(fixture.identity)
        if payload != fixture.expected_payload:
            raise AssertionError("metadata_payload_mismatch")
        if provider.normalize(payload, fixture.identity) != fixture.expected_metadata:
            raise AssertionError("metadata_normalization_mismatch")
        _assert_module_error(
            lambda: provider.fetch(fixture.invalid_identity), fixture.expected_error_code
        )
    finally:
        _close_twice(provider)

    policy = registration.retention()
    try:
        actual_policy = policy.retention_for(fixture.created_at)
        if actual_policy != fixture.expected_policy:
            raise AssertionError("metadata_retention_policy_mismatch")
        subject = RetentionSubject(identity=fixture.identity, policy=actual_policy)
        if policy.plan(subject, fixture.now) != fixture.expected_action:
            raise AssertionError("metadata_retention_action_mismatch")
        if policy.export_warning(actual_policy, fixture.now) != fixture.expected_warning:
            raise AssertionError("metadata_export_warning_mismatch")
    finally:
        _close_twice(policy)


def assert_release_registration_conforms(
    registration: ReleaseProviderRegistration,
    fixture: ReleaseConformanceFixture,
) -> None:
    StaticModuleRegistry.create(release=(registration,))
    environment = resolve_module_environment(registration.manifest, fixture.environment)
    provider = registration.build(environment)
    try:
        provider.validate()
        candidates = provider.search(fixture.query)
        if candidates != fixture.expected_candidates or len(candidates) > fixture.query.limit:
            raise AssertionError("release_search_result_mismatch")
        artifact = provider.resolve(candidates[0].selection)
        if artifact != fixture.expected_artifact:
            raise AssertionError("release_artifact_mismatch")
        _assert_artifact_declared(registration.manifest.capabilities, artifact)
        _assert_module_error(
            lambda: provider.resolve(fixture.invalid_selection), fixture.expected_error_code
        )
    finally:
        _close_twice(provider)


def assert_download_registration_conforms(
    registration: DownloadClientRegistration,
    fixture: DownloadClientConformanceFixture,
) -> None:
    StaticModuleRegistry.create(download=(registration,))
    environment = resolve_module_environment(registration.manifest, fixture.environment)
    client = registration.build(environment)
    try:
        client.validate()
        if client.list_destinations() != fixture.expected_destinations:
            raise AssertionError("download_destination_mismatch")
        compatible = tuple(
            artifact
            for artifact in fixture.artifacts
            if _artifact_kind(artifact) in registration.manifest.capabilities
        )
        declared_artifacts = registration.manifest.capabilities & {"magnet", "torrent"}
        if {_artifact_kind(artifact) for artifact in compatible} != declared_artifacts:
            raise AssertionError("download_fixture_capability_mismatch")
        for artifact in compatible:
            if (
                client.submit(artifact, fixture.destination, fixture.correlation)
                != fixture.expected_submission
            ):
                raise AssertionError("download_submission_mismatch")
        if client.find_by_correlation(fixture.correlation) != fixture.expected_correlation:
            raise AssertionError("download_correlation_mismatch")
        _assert_module_error(
            lambda: client.submit(compatible[0], fixture.invalid_destination, fixture.correlation),
            fixture.expected_error_code,
        )
    finally:
        _close_twice(client)


def _artifact_kind(artifact: DownloadArtifact) -> str:
    if isinstance(artifact, MagnetArtifact):
        return "magnet"
    if isinstance(artifact, TorrentArtifact):
        return "torrent"
    raise AssertionError("download_artifact_unknown")


def _assert_artifact_declared(capabilities: frozenset[str], artifact: DownloadArtifact) -> None:
    if _artifact_kind(artifact) not in capabilities:
        raise AssertionError("release_artifact_capability_undeclared")


__all__ = [
    "DownloadClientConformanceFixture",
    "MetadataConformanceFixture",
    "ReleaseConformanceFixture",
    "assert_download_registration_conforms",
    "assert_metadata_registration_conforms",
    "assert_release_registration_conforms",
]
