"""Real SQL integration tests for the acquisition bounded context."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier
from typing import cast

import pytest
from media_finder.domain import CatalogService
from media_finder.models import DownloadClientInstance, MetadataRevision
from media_finder.sdk.types import MediaKind, NormalizedMetadata, Provenance
from media_finder.system_clients import SYSTEM_QBITTORRENT_ID
from media_finder_core.acquisition import (
    AcquisitionCommands,
    AcquisitionQueries,
    AcquisitionRequest,
    AcquisitionStatus,
    DestinationUnavailable,
    ModuleVersionSnapshot,
    ReleaseSelectionCache,
    ReleaseSelectionService,
)
from media_finder_core.acquisition.persistence import (
    SqlAlchemyAcquisitionQueries,
    SqlAlchemyAcquisitionUnitOfWork,
)
from media_finder_core.catalog.persistence import SqlAlchemyCatalogQueries
from media_finder_core.platform.database import create_database, migrate_to_head, session_factory
from media_finder_sdk import (
    CorrelationResult,
    DownloadDestination,
    MagnetArtifact,
    ModuleError,
    ModuleFailureCategory,
    PrivateReleaseSelection,
    ReleaseCandidate,
    ReleaseSearchQuery,
    SafeReleaseSnapshot,
    SubmissionResult,
)
from sqlalchemy.orm import Session, sessionmaker


class _ReleaseProvider:
    def __init__(self, title: str = "Fixture.Release.2026") -> None:
        self.title = title
        self.resolve_calls = 0
        self.resolve_error: ModuleError | None = None

    def validate(self) -> None: ...

    def search(self, query: ReleaseSearchQuery) -> tuple[ReleaseCandidate, ...]:
        return (
            ReleaseCandidate(
                snapshot=SafeReleaseSnapshot(
                    title=self.title,
                    indexer="Fixture Indexer",
                    guid="fixture:release-1",
                    infohash="a" * 40,
                    source_page_url="https://indexer.example/releases/1",
                ),
                selection=PrivateReleaseSelection.from_bytes(query.query.encode()),
            ),
        )

    def resolve(self, selection: PrivateReleaseSelection) -> MagnetArtifact:
        assert selection.payload()
        self.resolve_calls += 1
        if self.resolve_error is not None:
            raise self.resolve_error
        return MagnetArtifact(uri=f"magnet:?xt=urn:btih:{'a' * 40}")

    def close(self) -> None: ...


class _DownloadClient:
    def __init__(
        self,
        queries: SqlAlchemyAcquisitionQueries,
        *,
        barrier: Barrier | None = None,
    ) -> None:
        self.queries = queries
        self.barrier = barrier
        self.destinations = (DownloadDestination(key="anime", label="Anime"),)
        self.submissions: list[str] = []
        self.lookup = "absent"
        self.timeout = False

    def validate(self) -> None: ...

    def list_destinations(self) -> tuple[DownloadDestination, ...]:
        if self.barrier is not None:
            self.barrier.wait(timeout=10)
        return self.destinations

    def submit(
        self, artifact: MagnetArtifact, destination: str, correlation: str
    ) -> SubmissionResult:
        assert artifact.uri.startswith("magnet:?")
        assert destination == "anime"
        pending = self.queries.get(correlation.removeprefix("mf-acq-"))
        assert pending is not None and pending.status is AcquisitionStatus.PENDING
        self.submissions.append(correlation)
        if self.timeout:
            raise ModuleError(
                category=ModuleFailureCategory.TIMEOUT,
                code="submission_timeout",
            )
        return SubmissionResult(
            accepted=True,
            external_task_id="client-task-1",
            correlation=correlation,
        )

    def find_by_correlation(self, correlation: str) -> CorrelationResult:
        if self.lookup == "found":
            return CorrelationResult(
                found=True,
                correlation=correlation,
                external_task_id="accepted-before-timeout",
            )
        return CorrelationResult(
            found=False,
            correlation=correlation,
            conclusive=self.lookup != "inconclusive",
        )

    def close(self) -> None: ...


def _seed(database: Session) -> tuple[str, str, str]:
    normalized = NormalizedMetadata(
        kind=MediaKind.MOVIE,
        titles={"en": "Fixture"},
        year=2026,
        provenance=Provenance(
            provider_key="manual",
            external_id="00000000-0000-4000-8000-000000000001",
            locale="en",
        ),
    )
    item = CatalogService(database).create_manual_item(normalized)
    revision = cast(MetadataRevision, item.current_revision)
    instance = database.get(DownloadClientInstance, SYSTEM_QBITTORRENT_ID)
    assert instance is not None
    return item.id, revision.id, instance.id


def _services(
    database: Session,
    *,
    provider: _ReleaseProvider | None = None,
    client: _DownloadClient | None = None,
    barrier: Barrier | None = None,
) -> tuple[AcquisitionCommands, AcquisitionQueries, ReleaseSelectionService, _DownloadClient]:
    sessions = sessionmaker(bind=database.get_bind(), expire_on_commit=False)
    selected_provider = provider or _ReleaseProvider()
    releases = ReleaseSelectionService(
        provider=selected_provider,
        cache=ReleaseSelectionCache(),
    )
    queries = SqlAlchemyAcquisitionQueries(
        sessions,
        legacy_download_client_instance_id=SYSTEM_QBITTORRENT_ID,
    )
    selected_client = client or _DownloadClient(queries, barrier=barrier)
    commands = AcquisitionCommands(
        query_port=queries,
        unit_of_work=SqlAlchemyAcquisitionUnitOfWork(
            sessions,
            legacy_download_client_instance_id=SYSTEM_QBITTORRENT_ID,
        ),
        catalog=SqlAlchemyCatalogQueries(sessions),
        releases=releases,
        download_client=selected_client,
        release_provider=ModuleVersionSnapshot("release-provider", "1.2.3"),
        download_client_module=ModuleVersionSnapshot("download-client", "4.5.6"),
        clock=lambda: datetime.now(UTC),
    )
    return commands, AcquisitionQueries(query_port=queries), releases, selected_client


def _request(item_id: str, revision_id: str, token: str, key: str) -> AcquisitionRequest:
    return AcquisitionRequest(
        media_item_id=item_id,
        metadata_revision_id=revision_id,
        destination="anime",
        release_token=token,
        idempotency_key=key,
        naming_profile="jellyfin-v1",
    )


def test_sql_submission_persists_pending_snapshot_before_exact_client_handoff(
    database: Session,
) -> None:
    item_id, revision_id, _instance_id = _seed(database)
    commands, queries, releases, client = _services(database)
    token = releases.search(ReleaseSearchQuery(query="Fixture"))[0].token

    first = commands.submit(_request(item_id, revision_id, token, "form-1"))
    duplicate = commands.submit(
        replace(_request(item_id, revision_id, token, "form-1"), release_token="consumed")
    )

    assert duplicate == first
    assert first.status is AcquisitionStatus.SUBMITTED
    assert first.release_provider == ModuleVersionSnapshot("release-provider", "1.2.3")
    assert first.download_client == ModuleVersionSnapshot("download-client", "4.5.6")
    assert first.release_snapshot.title == "Fixture.Release.2026"
    assert client.submissions == [first.correlation]
    assert queries.get(first.id) == first


def test_live_destination_drift_does_not_create_or_consume_an_acquisition(
    database: Session,
) -> None:
    item_id, revision_id, _instance_id = _seed(database)
    commands, queries, releases, client = _services(database)
    client.destinations = (DownloadDestination(key="movies", label="Movies"),)
    token = releases.search(ReleaseSearchQuery(query="Fixture"))[0].token

    with pytest.raises(DestinationUnavailable):
        commands.submit(_request(item_id, revision_id, token, "drift"))

    assert queries.pending_after_startup() == ()
    assert releases.inspect(token).title == "Fixture.Release.2026"


@pytest.mark.parametrize(
    ("lookup", "status", "failure"),
    [
        ("found", AcquisitionStatus.SUBMITTED, None),
        ("absent", AcquisitionStatus.FAILED, "submission_timeout_not_found"),
        ("inconclusive", AcquisitionStatus.PENDING, None),
    ],
)
def test_sql_timeout_uses_exact_lookup_and_manual_reconcile_only_changes_pending(
    database: Session,
    lookup: str,
    status: AcquisitionStatus,
    failure: str | None,
) -> None:
    item_id, revision_id, _instance_id = _seed(database)
    commands, queries, releases, client = _services(database)
    client.timeout = True
    client.lookup = lookup
    token = releases.search(ReleaseSearchQuery(query="Fixture"))[0].token

    result = commands.submit(_request(item_id, revision_id, token, f"timeout-{lookup}"))

    assert result.status is status
    assert result.failure_code == failure
    assert client.submissions == [result.correlation]
    if result.status is AcquisitionStatus.PENDING:
        assert queries.pending_after_startup() == (result,)
        client.lookup = "found"
        assert commands.reconcile(result.id).status is AcquisitionStatus.SUBMITTED


def test_real_sql_idempotency_race_creates_and_submits_once(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'acquisition-race.db'}"
    migrate_to_head(url)
    engine = create_database(url)
    sessions = session_factory(engine)
    with sessions() as database:
        item_id, revision_id, _instance_id = _seed(database)

    barrier = Barrier(2)
    contexts: list[tuple[AcquisitionCommands, ReleaseSelectionService, _DownloadClient]] = []
    with sessions() as database:
        for index in range(2):
            provider = _ReleaseProvider(f"Race.Release.{index}")
            commands, _queries, releases, client = _services(
                database,
                provider=provider,
                barrier=barrier,
            )
            contexts.append((commands, releases, client))
    tokens = [
        releases.search(ReleaseSearchQuery(query=f"Race-{index}"))[0].token
        for index, (_commands, releases, _client) in enumerate(contexts)
    ]

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                commands.submit,
                _request(item_id, revision_id, tokens[index], "race-key"),
            )
            for index, (commands, _releases, _client) in enumerate(contexts)
        ]
        results = [future.result(timeout=15) for future in futures]

    assert results[0].id == results[1].id
    assert sum(len(client.submissions) for _commands, _releases, client in contexts) == 1
    with sessions() as database:
        _commands, queries, _releases, _client = _services(database)
        persisted = queries.get(results[0].id)
    assert persisted.status is AcquisitionStatus.SUBMITTED
    engine.dispose()
