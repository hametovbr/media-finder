"""Capability-aware public conformance runners."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from media_finder_sdk import (
    CorrelationResult,
    DownloadArtifact,
    DownloadClient,
    DownloadClientConformanceFixture,
    DownloadClientRegistration,
    DownloadDestination,
    ExportWarning,
    MagnetArtifact,
    MediaKind,
    MetadataConformanceFixture,
    MetadataIdentity,
    MetadataProvider,
    MetadataProviderRegistration,
    MetadataRetentionPolicy,
    MetadataSearchQuery,
    MetadataSearchResult,
    ModuleError,
    ModuleFailureCategory,
    ModuleKind,
    NormalizedMetadata,
    PrivateReleaseSelection,
    Provenance,
    ProviderPayload,
    ReleaseCandidate,
    ReleaseConformanceFixture,
    ReleaseProvider,
    ReleaseProviderRegistration,
    ReleaseSearchQuery,
    ResolvedModuleEnvironment,
    RetentionAction,
    RetentionActionKind,
    RetentionPolicy,
    RetentionSubject,
    SafeReleaseSnapshot,
    SubmissionResult,
    assert_download_registration_conforms,
    assert_metadata_registration_conforms,
    assert_release_registration_conforms,
    parse_manifest,
)
from pydantic import ValidationError

from .fixtures import manifest_toml


class _Lifecycle:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _Metadata(_Lifecycle):
    def __init__(
        self,
        result: MetadataSearchResult,
        payload: ProviderPayload,
        normalized: NormalizedMetadata,
    ) -> None:
        super().__init__()
        self.result = result
        self.payload = payload
        self.normalized = normalized

    def validate(self) -> None: ...

    def search(self, query: MetadataSearchQuery) -> tuple[MetadataSearchResult, ...]:
        return (self.result,)

    def fetch(self, identity: MetadataIdentity) -> ProviderPayload:
        if identity.external_id == "invalid":
            raise ModuleError(
                category=ModuleFailureCategory.INVALID_IDENTITY,
                code="fixture_identity_invalid",
            )
        return self.payload

    def normalize(self, payload: ProviderPayload, identity: MetadataIdentity) -> NormalizedMetadata:
        return self.normalized


class _Retention(_Lifecycle):
    def __init__(self, policy: RetentionPolicy, action: RetentionAction) -> None:
        super().__init__()
        self.policy = policy
        self.action = action

    def retention_for(self, created_at: datetime) -> RetentionPolicy:
        return self.policy

    def plan(self, subject: RetentionSubject, now: datetime) -> RetentionAction:
        return self.action

    def export_warning(self, policy: RetentionPolicy, now: datetime) -> ExportWarning | None:
        return None


class _Release(_Lifecycle):
    def __init__(self, candidate: ReleaseCandidate, artifact: MagnetArtifact) -> None:
        super().__init__()
        self.candidate = candidate
        self.artifact = artifact

    def validate(self) -> None: ...

    def search(self, query: ReleaseSearchQuery) -> tuple[ReleaseCandidate, ...]:
        return (self.candidate,)

    def resolve(self, selection: PrivateReleaseSelection) -> MagnetArtifact:
        if selection.payload() == b"invalid":
            raise ModuleError(
                category=ModuleFailureCategory.INVALID_REQUEST,
                code="fixture_selection_invalid",
            )
        return self.artifact


class _Download(_Lifecycle):
    def validate(self) -> None: ...

    def list_destinations(self) -> tuple[DownloadDestination, ...]:
        return (DownloadDestination(key="movies", label="Movies"),)

    def submit(
        self, artifact: DownloadArtifact, destination: str, correlation: str
    ) -> SubmissionResult:
        if destination == "invalid":
            raise ModuleError(
                category=ModuleFailureCategory.INVALID_REQUEST,
                code="fixture_destination_invalid",
            )
        return SubmissionResult(accepted=True, external_task_id="task-1", correlation=correlation)

    def find_by_correlation(self, correlation: str) -> CorrelationResult:
        return CorrelationResult(
            found=True,
            correlation=correlation,
            external_task_id="task-1",
            conclusive=True,
        )


def test_metadata_search_result_previews_are_optional_and_typed() -> None:
    enriched = MetadataSearchResult(
        provider_id="fixture-metadata",
        external_id="1",
        media_kind=MediaKind.MOVIE,
        title="Fixture",
        year=2026,
        locale="en",
        description="A preview description.",
        poster_url="https://images.example.test/posters/fixture.jpg",
    )

    assert enriched.model_dump(mode="json") == {
        "provider_id": "fixture-metadata",
        "external_id": "1",
        "media_kind": "movie",
        "title": "Fixture",
        "year": 2026,
        "locale": "en",
        "description": "A preview description.",
        "poster_url": "https://images.example.test/posters/fixture.jpg",
    }

    without_previews = MetadataSearchResult.model_validate(
        {
            "provider_id": "fixture-metadata",
            "external_id": "2",
            "media_kind": "series",
            "title": "Fixture Series",
            "locale": "en",
        }
    )
    assert without_previews.description is None
    assert without_previews.poster_url is None

    with pytest.raises(ValidationError):
        MetadataSearchResult(
            provider_id="fixture-metadata",
            external_id="3",
            media_kind=MediaKind.MOVIE,
            title="Invalid poster",
            locale="en",
            poster_url="not a URL",
        )


def test_metadata_registration_conformance_uses_configuration_free_retention() -> None:
    identity = MetadataIdentity(
        provider_id="fixture-metadata",
        external_id="1",
        media_kind=MediaKind.MOVIE,
        locale="en",
    )
    result = MetadataSearchResult(
        provider_id="fixture-metadata",
        external_id="1",
        media_kind=MediaKind.MOVIE,
        title="Fixture",
        locale="en",
    )
    payload = ProviderPayload(data={"id": 1})
    normalized = NormalizedMetadata(
        kind=MediaKind.MOVIE,
        titles={"en": "Fixture"},
        provenance=Provenance(provider_id="fixture-metadata", external_id="1", locale="en"),
    )
    policy = RetentionPolicy()
    action = RetentionAction(kind=RetentionActionKind.NONE)
    providers: list[_Metadata] = []
    policies: list[_Retention] = []

    def build_metadata(_environment: ResolvedModuleEnvironment) -> MetadataProvider:
        provider = _Metadata(result, payload, normalized)
        providers.append(provider)
        return provider

    def build_retention() -> MetadataRetentionPolicy:
        retention = _Retention(policy, action)
        policies.append(retention)
        return retention

    registration = MetadataProviderRegistration(
        manifest=parse_manifest(
            manifest_toml(
                module_id="fixture-metadata",
                capabilities=("search", "fetch", "normalize", "retention"),
            )
        ),
        build=build_metadata,
        retention=build_retention,
    )
    fixture = MetadataConformanceFixture(
        environment={},
        query=MetadataSearchQuery(query="Fixture", locale="en"),
        expected_results=(result,),
        identity=identity,
        expected_payload=payload,
        expected_metadata=normalized,
        invalid_identity=identity.model_copy(update={"external_id": "invalid"}),
        expected_error_code="fixture_identity_invalid",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        now=datetime(2026, 1, 2, tzinfo=UTC),
        expected_policy=policy,
        expected_action=action,
        expected_warning=None,
    )

    assert_metadata_registration_conforms(registration, fixture)

    assert providers[0].closed
    assert policies[0].closed


def test_release_and_magnet_only_download_conformance_are_capability_aware() -> None:
    selection = PrivateReleaseSelection.from_bytes(b"selection")
    candidate = ReleaseCandidate(
        snapshot=SafeReleaseSnapshot(title="Fixture", indexer="Indexer"),
        selection=selection,
    )
    artifact = MagnetArtifact(uri="magnet:?xt=urn:btih:0123456789abcdef")
    releases: list[_Release] = []

    def build_release(_environment: ResolvedModuleEnvironment) -> ReleaseProvider:
        release = _Release(candidate, artifact)
        releases.append(release)
        return release

    release_registration = ReleaseProviderRegistration(
        manifest=parse_manifest(
            manifest_toml(
                module_id="fixture-release",
                module_kind=ModuleKind.RELEASE_PROVIDER,
                capabilities=("search", "resolve", "magnet"),
            )
        ),
        build=build_release,
    )
    release_fixture = ReleaseConformanceFixture(
        environment={},
        query=ReleaseSearchQuery(query="Fixture"),
        expected_candidates=(candidate,),
        expected_artifact=artifact,
        invalid_selection=PrivateReleaseSelection.from_bytes(b"invalid"),
        expected_error_code="fixture_selection_invalid",
    )
    downloads: list[_Download] = []

    def build_download(_environment: ResolvedModuleEnvironment) -> DownloadClient:
        download = _Download()
        downloads.append(download)
        return download

    download_registration = DownloadClientRegistration(
        manifest=parse_manifest(
            manifest_toml(
                module_id="fixture-download",
                module_kind=ModuleKind.DOWNLOAD_CLIENT,
                capabilities=("destinations", "submit", "correlation", "magnet"),
            )
        ),
        build=build_download,
    )
    download_fixture = DownloadClientConformanceFixture(
        environment={},
        expected_destinations=(DownloadDestination(key="movies", label="Movies"),),
        artifacts=(artifact,),
        destination="movies",
        invalid_destination="invalid",
        correlation="mf-acq-fixture",
        expected_submission=SubmissionResult(
            accepted=True,
            external_task_id="task-1",
            correlation="mf-acq-fixture",
        ),
        expected_correlation=CorrelationResult(
            found=True,
            correlation="mf-acq-fixture",
            external_task_id="task-1",
            conclusive=True,
        ),
        expected_error_code="fixture_destination_invalid",
    )

    assert_release_registration_conforms(release_registration, release_fixture)
    assert_download_registration_conforms(download_registration, download_fixture)

    assert releases[0].closed
    assert downloads[0].closed
