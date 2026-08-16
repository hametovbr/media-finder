from collections.abc import Iterator
from pathlib import Path

import pytest
from media_finder_core.platform.database import create_database, migrate_to_head, session_factory
from media_finder_sdk import (
    CorrelationResult,
    DownloadArtifact,
    DownloadDestination,
    MediaKind,
    MetadataIdentity,
    MetadataSearchQuery,
    MetadataSearchResult,
    ModuleError,
    ModuleFailureCategory,
    ModuleKind,
    ModuleManifest,
    NormalizedMetadata,
    Provenance,
    ProviderPayload,
    SubmissionResult,
)
from pydantic import BaseModel
from sqlalchemy.orm import Session


@pytest.fixture
def database(tmp_path: Path) -> Iterator[Session]:
    url = f"sqlite:///{tmp_path / 'media-finder.db'}"
    engine = create_database(url)
    migrate_to_head(url)
    with session_factory(engine)() as session:
        yield session
    engine.dispose()


class EmptyConfig(BaseModel):
    pass


class FakeProvider:
    manifest = ModuleManifest(
        module_id="fixture-provider",
        module_kind=ModuleKind.METADATA_PROVIDER,
        module_version="1.0.0",
        sdk_compatibility=">=1,<2",
        contract_version="1",
        name_key="fixture.provider",
        capabilities=frozenset({"search", "fetch", "normalize"}),
        translation_keys=frozenset({"fixture.provider"}),
    )

    def validate(self) -> None:
        return None

    def search(self, query: MetadataSearchQuery) -> tuple[MetadataSearchResult, ...]:
        return (
            MetadataSearchResult(
                provider_id=self.manifest.module_id,
                external_id="1",
                media_kind=MediaKind.MOVIE,
                title=query.query,
                locale=query.locale,
            ),
        )

    def fetch(self, identity: MetadataIdentity) -> ProviderPayload:
        if identity.external_id == "invalid":
            raise ModuleError(
                category=ModuleFailureCategory.INVALID_INPUT,
                code="fixture_identity_invalid",
            )
        return ProviderPayload(data={"title": "Fixture"})

    def normalize(
        self,
        payload: ProviderPayload,
        identity: MetadataIdentity,
    ) -> NormalizedMetadata:
        del payload
        return NormalizedMetadata(
            kind=identity.media_kind,
            titles={identity.locale: "Fixture"},
            provenance=Provenance(
                provider_id=self.manifest.module_id,
                external_id=identity.external_id,
                locale=identity.locale,
            ),
        )

    def close(self) -> None:
        return None


class FakeClient:
    manifest = ModuleManifest(
        module_id="fixture-client",
        module_kind=ModuleKind.DOWNLOAD_CLIENT,
        module_version="1.0.0",
        sdk_compatibility=">=1,<2",
        contract_version="1",
        name_key="fixture.client",
        capabilities=frozenset({"magnet", "torrent"}),
        translation_keys=frozenset({"fixture.client"}),
    )

    def __init__(self) -> None:
        self.tasks: dict[str, str] = {}

    def validate(self) -> None:
        return None

    def list_destinations(self) -> tuple[DownloadDestination, ...]:
        return (DownloadDestination(key="fixture", label="Fixture"),)

    def submit(
        self, artifact: DownloadArtifact, destination: str, correlation: str
    ) -> SubmissionResult:
        del artifact
        self.tasks[correlation] = destination
        return SubmissionResult(accepted=True, external_task_id="1", correlation=correlation)

    def find_by_correlation(self, correlation: str) -> CorrelationResult:
        return CorrelationResult(
            found=correlation in self.tasks,
            correlation=correlation,
            external_task_id="1" if correlation in self.tasks else None,
        )

    def close(self) -> None:
        return None


@pytest.fixture
def fake_provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def fake_client() -> FakeClient:
    return FakeClient()
