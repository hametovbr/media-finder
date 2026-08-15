from dataclasses import replace
from typing import cast
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from media_finder.acquisition import (
    AcquisitionRequest,
    AcquisitionService,
    DestinationUnavailable,
    create_download_client_instance,
)
from media_finder.domain import CatalogService
from media_finder.models import Acquisition, DownloadClientInstance, MetadataRevision
from media_finder.modules.qbittorrent import QbittorrentClient, QbittorrentConfig
from media_finder.prowlarr import ExpiredSearchToken, ProwlarrAdapter, SearchResultCache
from media_finder.sdk.errors import ModuleError
from media_finder.sdk.types import (
    CorrelationResult,
    DownloadDestination,
    MediaKind,
    NormalizedMetadata,
    Provenance,
    SubmissionResult,
)


class SearchTransport:
    def search(self, query: str, filters: dict[str, str]) -> list[dict[str, object]]:
        return [
            {
                "protocol": "torrent",
                "title": "Fixture.Release.2026",
                "indexer": "Fixture Indexer",
                "magnetUrl": "magnet:?xt=urn:btih:" + "a" * 40,
                "guid": "fixture:release-1",
                "guidIsPublic": True,
                "infoHash": "a" * 40,
                "infoUrl": "https://indexer.example/releases/1?passkey=never-store",
                "publicRoutePath": True,
                "normalizedPublicPath": "/releases/1",
            }
        ]

    def fetch_torrent(self, url: str) -> bytes:
        raise AssertionError("magnet result must not fetch a torrent file")


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
    instance = create_download_client_instance(
        database,
        name="Home qBittorrent",
        module_key="qbittorrent",
        config_payload={
            "base_url": "https://qb.example.test",
            "username_ref": "env:QB_USER",
            "password_ref": "env:QB_PASSWORD",
        },
    )
    return item.id, revision.id, instance


def search_token() -> tuple[ProwlarrAdapter, str]:
    prowlarr = ProwlarrAdapter(SearchTransport(), SearchResultCache())
    token = prowlarr.search("Fixture", {})[0].token
    return prowlarr, token


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
    assert first.source_page_url == "https://indexer.example"
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


@pytest.mark.parametrize(
    "payload",
    [
        {
            "base_url": "https://qb.example.test",
            "username_ref": "env:QB_USER",
            "password_ref": "env:QB_PASSWORD",
            "api_key": "literal-secret",
        },
        {
            "base_url": "https://qb.example.test",
            "username_ref": "env:QB_USER",
            "password_ref": "env:QB_PASSWORD",
            "credential": "literal-secret",
        },
        {
            "base_url": "https://qb.example.test",
            "username_ref": "env:QB_USER",
            "password_ref": "env:QB_PASSWORD",
            "nested": {"password": "literal-secret"},
        },
        {
            "base_url": "https://qb.example.test",
            "username_ref": "env:qb-user",
            "password_ref": "env:QB_PASSWORD",
        },
        {
            "base_url": "https://qb.example.test/api/passkey-literal-secret",
            "username_ref": "env:QB_USER",
            "password_ref": "env:QB_PASSWORD",
        },
    ],
)
def test_download_client_instance_uses_selected_module_typed_config(
    database: Session, payload: dict[str, object]
) -> None:
    with pytest.raises(ValueError):
        create_download_client_instance(
            database,
            name="Unsafe",
            module_key="qbittorrent",
            config_payload=payload,
        )

    assert database.scalar(select(DownloadClientInstance)) is None


def test_download_client_instance_persists_only_normalized_references(
    database: Session,
) -> None:
    instance = create_download_client_instance(
        database,
        name="Safe",
        module_key="qbittorrent",
        config_payload={
            "base_url": "https://qb.example.test",
            "username_ref": "env:QB_USER",
            "password_ref": "env:QB_PASSWORD",
        },
    )

    assert instance.config_payload == {
        "base_url": "https://qb.example.test/",
        "username_ref": "env:QB_USER",
        "password_ref": "env:QB_PASSWORD",
    }
    assert "literal" not in repr(instance.config_payload)


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

    with pytest.raises(ExpiredSearchToken):
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

    second_token = prowlarr.search("Fixture", {})[0].token
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
