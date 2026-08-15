import asyncio

import pytest
from media_finder_control import ControlFailure
from media_finder_control.models import AcquisitionSubmissionRequest, ReleaseSearchRequest
from sqlalchemy.orm import Session, sessionmaker

from media_finder.control_gateway import BackendControlGateway
from media_finder.domain import CatalogService, RevisionInput
from media_finder.models import Acquisition, DownloadClientInstance
from media_finder.prowlarr import ProwlarrAdapter, SearchResultCache
from media_finder.sdk.types import MediaKind, NormalizedMetadata, Provenance
from media_finder.system_clients import SYSTEM_QBITTORRENT_ID, ensure_system_qbittorrent
from media_finder.ui_runtime import RuntimeResolver


class TorrentSearchTransport:
    def search(self, query: str, filters: dict[str, str]) -> list[dict[str, object]]:
        assert query == "Example"
        assert filters == {"indexerIds": "1,2"}
        return [
            {
                "protocol": "torrent",
                "title": "Example.Release.1080p",
                "indexer": "Fixture",
                "magnetUrl": "magnet:?xt=urn:btih:abc",
            },
            {
                "protocol": "usenet",
                "title": "Ignored",
                "downloadUrl": "https://example.test/ignored",
            },
        ]

    def fetch_torrent(self, url: str) -> bytes:
        raise AssertionError(url)


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
    prowlarr: ProwlarrAdapter | None,
    client,
) -> BackendControlGateway:
    sessions = sessionmaker(bind=database.get_bind(), expire_on_commit=False)
    runtime = RuntimeResolver(
        factory=None,
        providers={},
        prowlarr=prowlarr,
        client_loader=lambda instance: client,
    )
    return BackendControlGateway(
        sessions=sessions,
        cursor_secret=b"cursor-secret-for-tests",
        runtime=runtime,
    )


def test_release_search_destinations_and_idempotent_submission(
    database: Session, fake_client
) -> None:
    item = _item(database)
    ensure_system_qbittorrent(database)
    prowlarr = ProwlarrAdapter(TorrentSearchTransport(), SearchResultCache())
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


def test_stale_destination_returns_current_values_without_consuming_release(
    database: Session, fake_client
) -> None:
    item = _item(database)
    ensure_system_qbittorrent(database)
    prowlarr = ProwlarrAdapter(TorrentSearchTransport(), SearchResultCache())
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
