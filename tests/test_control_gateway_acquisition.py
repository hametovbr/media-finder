import asyncio
from uuid import uuid4

import pytest
from media_finder.control_gateway import BackendControlGateway
from media_finder.domain import CatalogService, RevisionInput
from media_finder.integration_runtime import RuntimeResolver
from media_finder.models import Acquisition, DownloadClientInstance
from media_finder.sdk.types import MediaKind, NormalizedMetadata, Provenance
from media_finder.system_clients import SYSTEM_QBITTORRENT_ID, ensure_system_qbittorrent
from media_finder_control import ControlFailure
from media_finder_control.models import AcquisitionSubmissionRequest, ReleaseSearchRequest
from media_finder_core.acquisition import ReleaseSelectionCache, ReleaseSelectionService
from media_finder_sdk import (
    MagnetArtifact,
    PrivateReleaseSelection,
    ReleaseCandidate,
    ReleaseSearchFilter,
    ReleaseSearchQuery,
    SafeReleaseSnapshot,
)
from media_finder_server import create_legacy_module_registry, create_runtime_factory
from sqlalchemy.orm import Session, sessionmaker

REGISTRY = create_legacy_module_registry()
RELEASE_INTEGRATION = create_runtime_factory(environment={}).release_integration


class FixtureReleaseProvider:
    def validate(self) -> None:
        return None

    def search(self, query: ReleaseSearchQuery) -> tuple[ReleaseCandidate, ...]:
        assert query == ReleaseSearchQuery(
            query="Example",
            filters=(ReleaseSearchFilter(key="indexer-ids", values=("1", "2")),),
        )
        return (
            ReleaseCandidate(
                snapshot=SafeReleaseSnapshot(
                    title="Example.Release.1080p",
                    indexer="Fixture",
                ),
                selection=PrivateReleaseSelection.from_bytes(b"fixture-release"),
            ),
        )

    def resolve(self, selection: PrivateReleaseSelection) -> MagnetArtifact:
        assert selection.payload() == b"fixture-release"
        return MagnetArtifact(uri="magnet:?xt=urn:btih:abc")

    def close(self) -> None:
        return None


def _release_selection() -> ReleaseSelectionService:
    return ReleaseSelectionService(provider=FixtureReleaseProvider(), cache=ReleaseSelectionCache())


def _item(database: Session):
    catalog = CatalogService(database)
    item, _ = catalog.get_or_create_item("manual", "item-1", MediaKind.MOVIE)
    catalog.add_revision(
        item,
        RevisionInput.from_normalized(
            NormalizedMetadata(
                kind=MediaKind.MOVIE,
                titles={"en": "Example"},
                provenance=Provenance(provider_key="manual", external_id="item-1", locale="en"),
            )
        ),
    )
    return item


def _gateway(
    database: Session,
    *,
    prowlarr: ReleaseSelectionService | None,
    client,
    client_version: str | None = "9.8.7",
) -> BackendControlGateway:
    sessions = sessionmaker(bind=database.get_bind(), expire_on_commit=False)
    runtime = RuntimeResolver(
        factory=None,
        providers={},
        prowlarr=prowlarr,
        client_loader=lambda instance: client,
        download_client_versions=(
            {"qbittorrent": client_version} if client_version is not None else None
        ),
    )
    return BackendControlGateway(
        sessions=sessions,
        cursor_secret=b"cursor-secret-for-tests",
        runtime=runtime,
        registry=REGISTRY,
        release_integration=RELEASE_INTEGRATION,
    )


def test_release_search_destinations_and_idempotent_submission(
    database: Session, fake_client
) -> None:
    item = _item(database)
    ensure_system_qbittorrent(database)
    prowlarr = _release_selection()
    gateway = _gateway(database, prowlarr=prowlarr, client=fake_client)

    async def scenario() -> None:
        results = await gateway.search_releases(
            item_id=item.id,
            request=ReleaseSearchRequest(query="Example", indexer_ids=(1, 2)),
        )
        assert [result.title for result in results] == ["Example.Release.1080p"]
        destinations = await gateway.list_destinations()
        assert [destination.key for destination in destinations] == ["fixture"]
        request = AcquisitionSubmissionRequest(
            media_item_id=item.id,
            release_token=results[0].token,
            destination="fixture",
            idempotency_key="request-1",
        )
        first = await gateway.submit_acquisition(request=request)
        second = await gateway.submit_acquisition(request=request)
        assert first.id == second.id
        assert first.status == "submitted"
        assert list(fake_client.tasks) == [f"mf-acq-{first.id}"]

    asyncio.run(scenario())


def test_new_submission_requires_a_manifest_version_but_duplicate_does_not(
    database: Session, fake_client
) -> None:
    item = _item(database)
    ensure_system_qbittorrent(database)
    prowlarr = _release_selection()
    gateway = _gateway(database, prowlarr=prowlarr, client=fake_client)

    async def scenario() -> None:
        result = (
            await gateway.search_releases(
                item_id=item.id,
                request=ReleaseSearchRequest(query="Example", indexer_ids=(1, 2)),
            )
        )[0]
        request = AcquisitionSubmissionRequest(
            media_item_id=item.id,
            release_token=result.token,
            destination="fixture",
            idempotency_key="version-required",
        )
        first = await gateway.submit_acquisition(request=request)
        unversioned = _gateway(
            database,
            prowlarr=prowlarr,
            client=fake_client,
            client_version=None,
        )
        duplicate = await unversioned.submit_acquisition(request=request)
        assert duplicate.id == first.id

        fresh_result = (
            await unversioned.search_releases(
                item_id=item.id,
                request=ReleaseSearchRequest(query="Example", indexer_ids=(1, 2)),
            )
        )[0]
        fresh = AcquisitionSubmissionRequest(
            media_item_id=item.id,
            release_token=fresh_result.token,
            destination="fixture",
            idempotency_key="version-missing",
        )
        with pytest.raises(ControlFailure) as rejected:
            await unversioned.submit_acquisition(request=fresh)
        assert rejected.value.error.code == "download_client_version_unavailable"
        assert rejected.value.status == 503

    asyncio.run(scenario())


def test_stale_destination_returns_current_values_without_consuming_release(
    database: Session, fake_client
) -> None:
    item = _item(database)
    ensure_system_qbittorrent(database)
    prowlarr = _release_selection()
    gateway = _gateway(database, prowlarr=prowlarr, client=fake_client)

    async def scenario() -> None:
        result = (
            await gateway.search_releases(
                item_id=item.id,
                request=ReleaseSearchRequest(query="Example", indexer_ids=(1, 2)),
            )
        )[0]
        with pytest.raises(ControlFailure) as stale:
            await gateway.submit_acquisition(
                request=AcquisitionSubmissionRequest(
                    media_item_id=item.id,
                    release_token=result.token,
                    destination="removed",
                    idempotency_key="request-stale",
                )
            )
        assert stale.value.status == 409
        assert stale.value.error.code == "download_destination_unavailable"
        assert stale.value.error.details["destinations"] == [{"key": "fixture", "label": "Fixture"}]

        submitted = await gateway.submit_acquisition(
            request=AcquisitionSubmissionRequest(
                media_item_id=item.id,
                release_token=result.token,
                destination="fixture",
                idempotency_key="request-stale-retry",
            )
        )
        assert submitted.status == "submitted"

    asyncio.run(scenario())


def test_pending_reconcile_does_not_require_prowlarr(database: Session, fake_client) -> None:
    item = _item(database)
    instance = ensure_system_qbittorrent(database)
    acquisition = Acquisition(
        id=(acquisition_id := uuid4()),
        correlation=f"mf-acq-{acquisition_id}",
        release_provider_id="fixture-release",
        release_provider_version="1.0.0",
        download_client_module_id="qbittorrent",
        download_client_module_version="0.1.0",
        media_item_id=item.id,
        metadata_revision_id=item.current_revision_id,
        download_client_instance_id=SYSTEM_QBITTORRENT_ID,
        idempotency_key="pending-1",
        naming_profile="jellyfin-v1",
        status="pending",
        destination="fixture",
        release_title="Example.Release.1080p",
    )
    database.add(acquisition)
    database.commit()
    correlation = f"mf-acq-{acquisition.id}"
    fake_client.tasks[correlation] = "fixture"
    assert database.get(DownloadClientInstance, instance.id) is not None
    gateway = _gateway(database, prowlarr=None, client=fake_client)

    reconciled = asyncio.run(gateway.reconcile_acquisition(acquisition_id=str(acquisition.id)))
    assert reconciled.status == "submitted"
