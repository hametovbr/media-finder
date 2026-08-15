from dataclasses import replace
from typing import cast
from uuid import UUID

import httpx
import pytest
from media_finder_sdk import (
    MagnetArtifact as SDKMagnetArtifact,
)
from media_finder_sdk import (
    ModuleError as SDKModuleError,
)
from media_finder_sdk import (
    ModuleFailureCategory,
    PrivateReleaseSelection,
    ReleaseCandidate,
    ReleaseSearchQuery,
    SafeReleaseSnapshot,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from media_finder.acquisition import (
    AcquisitionRequest,
    AcquisitionService,
    DestinationUnavailable,
)
from media_finder.domain import CatalogService
from media_finder.models import Acquisition, DownloadClientInstance, MetadataRevision
from media_finder.modules.qbittorrent import QbittorrentClient, QbittorrentConfig
from media_finder.release_selection import (
    ReleaseSelectionCache,
    ReleaseSelectionExpired,
    ReleaseSelectionService,
)
from media_finder.sdk.errors import ModuleError
from media_finder.sdk.types import (
    CorrelationResult,
    DownloadDestination,
    MediaKind,
    NormalizedMetadata,
    Provenance,
    SubmissionResult,
)
from media_finder.system_clients import SYSTEM_QBITTORRENT_ID


class SearchProvider:
    def validate(self) -> None:
        return None

    def search(self, query: ReleaseSearchQuery) -> tuple[ReleaseCandidate, ...]:
        assert query.query == "Fixture"
        return (
            ReleaseCandidate(
                snapshot=SafeReleaseSnapshot(
                    title="Fixture.Release.2026",
                    indexer="Fixture Indexer",
                    guid="fixture:release-1",
                    infohash="a" * 40,
                    source_page_url="https://indexer.example/releases/1",
                ),
                selection=PrivateReleaseSelection.from_bytes(b"fixture-selection"),
            ),
        )

    def resolve(self, selection: PrivateReleaseSelection) -> SDKMagnetArtifact:
        assert selection.payload() == b"fixture-selection"
        return SDKMagnetArtifact(uri="magnet:?xt=urn:btih:" + "a" * 40)

    def close(self) -> None:
        return None


class FailingResolveProvider(SearchProvider):
    def resolve(self, selection: PrivateReleaseSelection) -> SDKMagnetArtifact:
        del selection
        raise SDKModuleError(
            category=ModuleFailureCategory.LIMIT_EXCEEDED,
            code="release_torrent_too_large",
        )


class AcceptingClient:
    def __init__(self, database: Session) -> None:
        self.database = database
        self.destinations = [DownloadDestination(key="anime", label="Anime")]
        self.submissions: list[tuple[str, str]] = []

    def list_destinations(self) -> list[DownloadDestination]:
        return self.destinations

    def submit(self, artifact, destination: str, correlation: str) -> SubmissionResult:
        pending = self.database.scalar(
            select(Acquisition).where(Acquisition.id == UUID(correlation.removeprefix("mf-acq-")))
        )
        assert pending is not None and pending.status == "pending"
        self.submissions.append((destination, correlation))
        return SubmissionResult(
            accepted=True, external_task_id="qb-task-1", correlation=correlation
        )

    def find_by_correlation(self, correlation: str) -> CorrelationResult:
        return CorrelationResult(found=False, correlation=correlation)


def seed(database: Session) -> tuple[str, str, DownloadClientInstance]:
    normalized = NormalizedMetadata(
        kind=MediaKind.MOVIE,
        titles={"en": "Fixture"},
        year=2026,
        provenance=Provenance(provider_key="manual", external_id="seed", locale="en"),
    )
    item = CatalogService(database).create_manual_item(normalized)
    revision = cast(MetadataRevision, item.current_revision)
    instance = database.get(DownloadClientInstance, SYSTEM_QBITTORRENT_ID)
    assert instance is not None and instance.system_owned
    return item.id, revision.id, instance


def search_token() -> tuple[ReleaseSelectionService, str]:
    releases = ReleaseSelectionService(SearchProvider(), ReleaseSelectionCache())
    token = releases.search(ReleaseSearchQuery(query="Fixture"))[0].token
    return releases, token


def test_sdk_release_failure_preserves_stable_module_code(database: Session) -> None:
    item_id, revision_id, instance = seed(database)
    releases = ReleaseSelectionService(FailingResolveProvider(), ReleaseSelectionCache())
    token = releases.search(ReleaseSearchQuery(query="Fixture"))[0].token
    client = AcceptingClient(database)

    acquisition = AcquisitionService(database, releases, lambda stored: client).submit(
        AcquisitionRequest(
            media_item_id=item_id,
            metadata_revision_id=revision_id,
            client_instance_id=instance.id,
            destination="anime",
            release_token=token,
            idempotency_key="sdk-release-failure",
        )
    )

    assert acquisition.status == "failed"
    assert acquisition.failure_code == "release_torrent_too_large"
    assert client.submissions == []


def test_submission_is_pending_first_exactly_correlated_and_idempotent(database: Session) -> None:
    item_id, revision_id, instance = seed(database)
    prowlarr, token = search_token()
    client = AcceptingClient(database)
    service = AcquisitionService(database, prowlarr, lambda stored: client)
    request = AcquisitionRequest(
        media_item_id=item_id,
        metadata_revision_id=revision_id,
        client_instance_id=instance.id,
        destination="anime",
        release_token=token,
        idempotency_key="browser-form-1",
    )

    first = service.submit(request)
    duplicate = service.submit(replace(request, release_token="already-gone"))

    assert duplicate.id == first.id
    assert first.status == "submitted"
    assert first.naming_profile == "jellyfin-v1"
    assert first.metadata_revision_id == revision_id
    assert first.destination == "anime"
    assert first.release_title == "Fixture.Release.2026"
    assert first.guid == "fixture:release-1"
    assert first.infohash == "a" * 40
    assert first.source_page_url == "https://indexer.example/releases/1"
    assert first.external_task_id == "qb-task-1"
    assert client.submissions == [("anime", f"mf-acq-{first.id}")]


def test_disappeared_destination_returns_current_live_choices_without_acquisition(
    database: Session,
) -> None:
    item_id, revision_id, instance = seed(database)
    prowlarr, token = search_token()
    client = AcceptingClient(database)
    client.destinations = [DownloadDestination(key="movies", label="Movies")]
    service = AcquisitionService(database, prowlarr, lambda stored: client)

    with pytest.raises(DestinationUnavailable) as rejected:
        service.submit(
            AcquisitionRequest(
                media_item_id=item_id,
                metadata_revision_id=revision_id,
                client_instance_id=instance.id,
                destination="anime",
                release_token=token,
                idempotency_key="browser-form-disappeared",
            )
        )

    assert [item.key for item in rejected.value.current_destinations] == ["movies"]
    assert database.scalar(select(Acquisition)) is None
    assert client.submissions == []


def test_database_exposes_only_empty_system_client_configuration(database: Session) -> None:
    instances = list(database.scalars(select(DownloadClientInstance)))

    assert len(instances) == 1
    assert instances[0].id == SYSTEM_QBITTORRENT_ID
    assert instances[0].system_owned is True
    assert instances[0].config_payload == {}


class RecoveryClient(AcceptingClient):
    def __init__(self, database: Session, lookup: str) -> None:
        super().__init__(database)
        self.lookup = lookup
        self.submit_calls = 0

    def submit(self, artifact, destination: str, correlation: str) -> SubmissionResult:
        self.submit_calls += 1
        raise ModuleError("submission_timeout", "must-not-escape passkey=secret")

    def find_by_correlation(self, correlation: str) -> CorrelationResult:
        if self.lookup == "found":
            return CorrelationResult(
                found=True,
                correlation=correlation,
                external_task_id="accepted-before-timeout",
            )
        if self.lookup == "absent":
            return CorrelationResult(found=False, correlation=correlation)
        return CorrelationResult(found=False, correlation=correlation, conclusive=False)


@pytest.mark.parametrize(
    ("lookup", "expected_status", "expected_failure"),
    [
        ("found", "submitted", None),
        ("absent", "failed", "submission_timeout_not_found"),
        ("inconclusive", "pending", None),
    ],
)
def test_timeout_is_resolved_by_exact_lookup_without_resubmission(
    database: Session,
    lookup: str,
    expected_status: str,
    expected_failure: str | None,
) -> None:
    item_id, revision_id, instance = seed(database)
    prowlarr, token = search_token()
    client = RecoveryClient(database, lookup)
    acquisition = AcquisitionService(database, prowlarr, lambda stored: client).submit(
        AcquisitionRequest(
            media_item_id=item_id,
            metadata_revision_id=revision_id,
            client_instance_id=instance.id,
            destination="anime",
            release_token=token,
            idempotency_key=f"timeout-{lookup}",
        )
    )

    assert acquisition.status == expected_status
    assert acquisition.failure_code == expected_failure
    assert client.submit_calls == 1
    if lookup == "found":
        assert acquisition.external_task_id == "accepted-before-timeout"


def test_restart_only_lists_pending_and_manual_reconcile_uses_exact_token(
    database: Session,
) -> None:
    item_id, revision_id, instance = seed(database)
    prowlarr, token = search_token()
    client = RecoveryClient(database, "inconclusive")
    first_service = AcquisitionService(database, prowlarr, lambda stored: client)
    pending = first_service.submit(
        AcquisitionRequest(
            media_item_id=item_id,
            metadata_revision_id=revision_id,
            client_instance_id=instance.id,
            destination="anime",
            release_token=token,
            idempotency_key="crash-pending",
        )
    )
    assert pending.status == "pending"

    restarted = AcquisitionService(database, prowlarr, lambda stored: client)
    rows = restarted.pending_after_startup()
    assert [row.id for row in rows] == [pending.id]
    assert client.submit_calls == 1

    client.lookup = "found"
    reconciled = restarted.reconcile(str(pending.id))
    assert reconciled.status == "submitted"
    assert client.submit_calls == 1
    assert reconciled.external_task_id == "accepted-before-timeout"


def test_failed_retry_requires_a_fresh_selection_and_creates_a_new_uuid(
    database: Session,
) -> None:
    item_id, revision_id, instance = seed(database)
    prowlarr, first_token = search_token()
    client = RecoveryClient(database, "absent")
    service = AcquisitionService(database, prowlarr, lambda stored: client)
    first = service.submit(
        AcquisitionRequest(
            media_item_id=item_id,
            metadata_revision_id=revision_id,
            client_instance_id=instance.id,
            destination="anime",
            release_token=first_token,
            idempotency_key="failed-attempt",
        )
    )
    assert first.status == "failed"

    with pytest.raises(ReleaseSelectionExpired):
        service.submit(
            AcquisitionRequest(
                media_item_id=item_id,
                metadata_revision_id=revision_id,
                client_instance_id=instance.id,
                destination="anime",
                release_token=first_token,
                idempotency_key="stale-token-retry",
            )
        )

    second_token = prowlarr.search(ReleaseSearchQuery(query="Fixture"))[0].token
    client.lookup = "found"
    second = service.submit(
        AcquisitionRequest(
            media_item_id=item_id,
            metadata_revision_id=revision_id,
            client_instance_id=instance.id,
            destination="anime",
            release_token=second_token,
            idempotency_key="explicit-retry",
        )
    )

    assert second.status == "submitted"
    assert second.id != first.id
    assert second_token != first_token
    assert client.submit_calls == 2


class HttpxTimeoutQbittorrentTransport:
    def __init__(self) -> None:
        self.submit_calls = 0
        self.lookup_calls = 0

    def authenticate(self, username: str, password: str) -> None:
        pass

    def list_categories(self) -> dict[str, str]:
        return {"anime": "/downloads/anime"}

    def add_magnet(self, uri: str, category: str, tag: str) -> str:
        self.submit_calls += 1
        raise httpx.ReadTimeout("passkey=raw-secret")

    def add_torrent(self, content: bytes, category: str, tag: str) -> str:
        return self.add_magnet("", category, tag)

    def find_by_tag(self, tag: str) -> list[dict[str, str]]:
        self.lookup_calls += 1
        return [{"hash": "a" * 40, "tags": tag}]


def test_real_httpx_timeout_performs_one_exact_lookup_and_never_resubmits(
    database: Session,
) -> None:
    item_id, revision_id, instance = seed(database)
    prowlarr, token = search_token()
    native = HttpxTimeoutQbittorrentTransport()
    client = QbittorrentClient(
        QbittorrentConfig(
            base_url="https://qb.example.test",
            username_ref="env:QB_USER",
            password_ref="env:QB_PASSWORD",
        ),
        native,
        lambda reference: "resolved-in-memory",
    )

    acquisition = AcquisitionService(database, prowlarr, lambda stored: client).submit(
        AcquisitionRequest(
            media_item_id=item_id,
            metadata_revision_id=revision_id,
            client_instance_id=instance.id,
            destination="anime",
            release_token=token,
            idempotency_key="real-httpx-timeout",
        )
    )

    assert acquisition.status == "submitted"
    assert acquisition.external_task_id == "a" * 40
    assert native.submit_calls == 1
    assert native.lookup_calls == 1
