from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import BaseModel
from sqlalchemy.orm import Session

from media_finder.db import create_database, migrate_to_head, session_factory
from media_finder.sdk.errors import ModuleError
from media_finder.sdk.types import (
    Attribution,
    CorrelationResult,
    DownloadDestination,
    ExportHeader,
    ExportWarning,
    MediaKind,
    MetadataSearchResult,
    ModuleKind,
    ModuleManifest,
    NormalizedMetadata,
    Provenance,
    RetentionAction,
    RetentionActionKind,
    RetentionPolicy,
    SubmissionResult,
)


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
        key="fixture-provider",
        version="1.0.0",
        contract_version="1",
        name_key="fixture.provider",
        capabilities=frozenset({"movie"}),
    )
    config_model = EmptyConfig

    def validate_config(self) -> None:
        EmptyConfig()

    def search(self, query: str, locale: str) -> list[MetadataSearchResult]:
        return [
            MetadataSearchResult(
                provider_key=self.manifest.key,
                external_id="1",
                kind=MediaKind.MOVIE,
                title=query,
                locale=locale,
            )
        ]

    def fetch(self, kind: str, external_id: str, locale: str) -> dict:
        if external_id == "invalid":
            raise ModuleError(code="fixture_identity_invalid", message="Fixture identity invalid")
        return {"title": "Fixture"}

    def normalize(self, payload, kind: str, external_id: str, locale: str) -> NormalizedMetadata:
        return NormalizedMetadata(
            kind=MediaKind(kind),
            titles={locale: "Fixture"},
            provenance=Provenance(
                provider_key=self.manifest.key, external_id=external_id, locale=locale
            ),
        )

    def attribution(self) -> Attribution:
        return Attribution(provider_key=self.manifest.key, notice="Fixture data")

    def retention_for(self, created_at) -> RetentionPolicy:
        return RetentionPolicy()

    def plan_retention(self, policy, now) -> RetentionAction:
        return RetentionAction(kind=RetentionActionKind.NONE)

    def export_warning(self, policy, now) -> ExportWarning | None:
        return ExportWarning(
            headers=(ExportHeader(name="Warning", value="299 Media Finder fixture"),)
        )


class FakeClient:
    manifest = ModuleManifest(
        key="fixture-client",
        version="1.0.0",
        contract_version="1",
        name_key="fixture.client",
        kind=ModuleKind.DOWNLOAD_CLIENT,
        capabilities=frozenset({"magnet", "torrent"}),
    )
    config_model = EmptyConfig

    def __init__(self) -> None:
        self.tasks: dict[str, str] = {}

    def validate_config(self) -> None:
        EmptyConfig()

    def list_destinations(self) -> list[DownloadDestination]:
        return [DownloadDestination(key="fixture", label="Fixture")]

    def submit(self, artifact, destination: str, correlation: str) -> SubmissionResult:
        self.tasks[correlation] = destination
        return SubmissionResult(accepted=True, external_task_id="1", correlation=correlation)

    def find_by_correlation(self, correlation: str) -> CorrelationResult:
        return CorrelationResult(
            found=correlation in self.tasks,
            correlation=correlation,
            external_task_id="1" if correlation in self.tasks else None,
        )


@pytest.fixture
def fake_provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def fake_client() -> FakeClient:
    return FakeClient()
