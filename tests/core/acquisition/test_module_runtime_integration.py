"""Runtime integration contract for generic release and download modules."""

from __future__ import annotations

import ast
import asyncio
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs
from uuid import UUID

import httpx
import pytest
from catalog_fixtures import CatalogFixture as CatalogService
from catalog_fixtures import RevisionInput
from media_finder_control import ControlFailure
from media_finder_control.models import AcquisitionSubmissionRequest, ReleaseSearchRequest
from media_finder_core.acquisition import (
    AcquisitionDraft,
    AcquisitionStatus,
    ModuleVersionSnapshot,
    ReleaseSelectionCache,
)
from media_finder_core.acquisition.persistence import (
    SqlAlchemyAcquisitionQueries,
    SqlAlchemyAcquisitionUnitOfWork,
)
from media_finder_core.platform import EphemeralCache
from media_finder_sdk import MediaKind, NormalizedMetadata, Provenance, SafeReleaseSnapshot
from media_finder_server.control_gateway import BackendControlGateway
from media_finder_server.modules import RuntimeModuleComposition, create_runtime_module_composition
from sqlalchemy.orm import Session, sessionmaker

ROOT = Path(__file__).parents[3]
FIRST_PARTY_ENVIRONMENT = {
    "PROWLARR_URL": "https://prowlarr.example.test/reverse/prowlarr",
    "PROWLARR_API_KEY": "prowlarr-key-never-log",
    "QBITTORRENT_URL": "https://qb.example.test/reverse/qb",
    "QBITTORRENT_USERNAME": "qb-user",
    "QBITTORRENT_PASSWORD": "qb-password-never-log",
}
INFOHASH = "0123456789abcdef0123456789abcdef01234567"
PENDING_ID = UUID("33333333-3333-4333-8333-333333333333")


class _FirstPartyTransport:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.expected_reconcile_correlation: str | None = None

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self._respond))

    def _respond(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/reverse/prowlarr/api/v1/system/status":
            assert request.headers["X-Api-Key"] == FIRST_PARTY_ENVIRONMENT["PROWLARR_API_KEY"]
            return httpx.Response(200, json={"version": "2.0.0"})
        if request.url.path == "/reverse/prowlarr/api/v1/search":
            return httpx.Response(
                200,
                json=[
                    {
                        "title": "Fixture.Release.2026.1080p",
                        "indexer": "Fixture Torrent Indexer",
                        "protocol": "torrent",
                        "guid": "fixture-guid",
                        "infoHash": INFOHASH,
                        "magnetUrl": f"magnet:?xt=urn:btih:{INFOHASH}",
                        "infoUrl": "https://indexer.example.test/release?secret=removed",
                    },
                    {
                        "title": "Ignored.Usenet",
                        "indexer": "Fixture Usenet Indexer",
                        "protocol": "usenet",
                        "downloadUrl": "https://prowlarr.example.test/download/fixture.nzb",
                    },
                ],
            )
        if request.url.path == "/reverse/qb/api/v2/auth/login":
            form = parse_qs(request.content.decode())
            assert form == {
                "username": [FIRST_PARTY_ENVIRONMENT["QBITTORRENT_USERNAME"]],
                "password": [FIRST_PARTY_ENVIRONMENT["QBITTORRENT_PASSWORD"]],
            }
            return httpx.Response(200, text="Ok.", headers={"set-cookie": "SID=fixture"})
        if request.url.path == "/reverse/qb/api/v2/torrents/categories":
            return httpx.Response(
                200,
                json={"anime": {"name": "anime", "savePath": "/downloads/anime"}},
            )
        if request.url.path == "/reverse/qb/api/v2/torrents/add":
            form = parse_qs(request.content.decode())
            assert form["category"] == ["anime"]
            assert form["tags"][0].startswith("mf-acq-")
            return httpx.Response(200, text="Ok.")
        if request.url.path == "/reverse/qb/api/v2/torrents/info":
            correlation = self.expected_reconcile_correlation
            assert correlation is not None
            assert request.url.params["tag"] == correlation
            return httpx.Response(
                200,
                json=[{"hash": INFOHASH, "tags": f"other, {correlation}"}],
            )
        return httpx.Response(404)


def _seed_item(database: Session):
    catalog = CatalogService(database)
    item, _ = catalog.get_or_create_item("manual", "runtime-item", MediaKind.MOVIE)
    catalog.add_revision(
        item,
        RevisionInput.from_normalized(
            NormalizedMetadata(
                kind=MediaKind.MOVIE,
                titles={"en": "Fixture"},
                provenance=Provenance(
                    provider_id="manual",
                    external_id="runtime-item",
                    locale="en",
                ),
            )
        ),
    )
    database.commit()
    return item


def _gateway(
    database: Session,
    composition: RuntimeModuleComposition,
) -> BackendControlGateway:
    return BackendControlGateway(
        sessions=sessionmaker(bind=database.get_bind(), expire_on_commit=False),
        cursor_secret=b"typed-module-runtime-test-secret",
        metadata_selections=EphemeralCache(),
        manual_drafts=EphemeralCache(),
        registry=composition.registry,
        module_runtime=composition.runtime,
        release_selections=composition.release_selections,
        release_manifest=composition.release_manifest,
        download_manifest=composition.download_manifest,
        environment=FIRST_PARTY_ENVIRONMENT,
    )


def test_first_party_round_trip_uses_only_typed_module_runtime_and_exact_versions(
    database: Session,
) -> None:
    item = _seed_item(database)
    transport = _FirstPartyTransport()
    composition = create_runtime_module_composition(
        environment=FIRST_PARTY_ENVIRONMENT,
        client_factory=transport.client,
        release_cache=ReleaseSelectionCache(),
    )
    gateway = _gateway(database, composition)

    async def scenario() -> tuple[str, str]:
        releases = await gateway.search_releases(
            item_id=item.id,
            request=ReleaseSearchRequest(query="Fixture", indexer_ids=()),
        )
        assert [(value.title, value.indexer) for value in releases] == [
            ("Fixture.Release.2026.1080p", "Fixture Torrent Indexer")
        ]
        destinations = await gateway.list_destinations()
        assert [(value.key, value.label) for value in destinations] == [("anime", "anime")]
        request = AcquisitionSubmissionRequest(
            media_item_id=item.id,
            release_token=releases[0].token,
            destination="anime",
            idempotency_key="typed-runtime-submit",
        )
        first = await gateway.submit_acquisition(request=request)
        duplicate = await gateway.submit_acquisition(request=request)
        assert duplicate.id == first.id
        assert first.status == "submitted"

        with pytest.raises(ControlFailure) as consumed:
            await gateway.submit_acquisition(
                request=AcquisitionSubmissionRequest(
                    media_item_id=item.id,
                    release_token=releases[0].token,
                    destination="anime",
                    idempotency_key="typed-runtime-consumed-token",
                )
            )
        assert consumed.value.status == 410
        assert consumed.value.error.code == "selection_expired"
        return first.id, releases[0].token

    try:
        acquisition_id, _token = asyncio.run(scenario())
        sessions = sessionmaker(bind=database.get_bind(), expire_on_commit=False)
        saved = SqlAlchemyAcquisitionQueries(sessions).get(acquisition_id)
        assert saved is not None
        assert saved.release_provider == ModuleVersionSnapshot(
            module_id="prowlarr", module_version="0.1.0"
        )
        assert saved.download_client == ModuleVersionSnapshot(
            module_id="qbittorrent", module_version="0.1.0"
        )
        assert saved.release_snapshot.infohash == INFOHASH
        assert str(saved.release_snapshot.source_page_url) == "https://indexer.example.test/"
        add_requests = [
            request
            for request in transport.requests
            if request.url.path == "/reverse/qb/api/v2/torrents/add"
        ]
        assert len(add_requests) == 1
    finally:
        composition.release_selections.close()
        composition.runtime.close()


def test_manual_reconcile_uses_persisted_download_module_without_release_provider(
    database: Session,
) -> None:
    item = _seed_item(database)
    sessions = sessionmaker(bind=database.get_bind(), expire_on_commit=False)
    draft = AcquisitionDraft(
        id=PENDING_ID,
        media_item_id=item.id,
        metadata_revision_id=item.current_revision_id,
        idempotency_key="typed-runtime-reconcile",
        naming_profile="jellyfin-v1",
        destination="anime",
        correlation=f"mf-acq-{PENDING_ID}",
        release_snapshot=SafeReleaseSnapshot(
            title="Pending.Release",
            indexer="Fixture Torrent Indexer",
        ),
        release_provider=ModuleVersionSnapshot(module_id="prowlarr", module_version="0.1.0"),
        download_client=ModuleVersionSnapshot(module_id="qbittorrent", module_version="0.1.0"),
        created_at=datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
    )
    with SqlAlchemyAcquisitionUnitOfWork(sessions).write() as repository:
        repository.create_pending_if_absent(draft)

    transport = _FirstPartyTransport()
    transport.expected_reconcile_correlation = draft.correlation
    environment = {
        key: value
        for key, value in FIRST_PARTY_ENVIRONMENT.items()
        if key.startswith("QBITTORRENT_")
    }
    composition = create_runtime_module_composition(
        environment=environment,
        client_factory=transport.client,
        release_cache=ReleaseSelectionCache(),
    )
    gateway = _gateway(database, composition)

    try:
        reconciled = asyncio.run(gateway.reconcile_acquisition(acquisition_id=str(PENDING_ID)))
        assert reconciled.status == AcquisitionStatus.SUBMITTED.value
        assert all(request.url.host != "prowlarr.example.test" for request in transport.requests)
        assert [
            request.url.path
            for request in transport.requests
            if request.url.path.endswith("/torrents/info")
        ] == ["/reverse/qb/api/v2/torrents/info"]
    finally:
        composition.release_selections.close()
        composition.runtime.close()


def test_server_acquisition_path_has_no_concrete_or_parallel_runtime_branch() -> None:
    gateway_path = (
        ROOT / "packages" / "core" / "src" / "media_finder_core" / "control" / "acquisition.py"
    )
    gateway_tree = ast.parse(gateway_path.read_text(encoding="utf-8"), filename=str(gateway_path))
    acquisition_methods = {
        "search_releases",
        "list_destinations",
        "submit_acquisition",
        "reconcile_acquisition",
    }
    selected = [
        node
        for node in ast.walk(gateway_tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name in acquisition_methods
    ]
    assert {node.name for node in selected} == acquisition_methods

    forbidden_identifiers = {
        "SYSTEM_QBITTORRENT_ID",
        "DownloadClientInstance",
        "_release_integration",
        "prowlarr",
        "core_download_client",
        "download_client_version",
    }
    violations: list[str] = []
    for method in selected:
        for node in ast.walk(method):
            if isinstance(node, ast.Name) and node.id in forbidden_identifiers:
                violations.append(f"acquisition.py:{method.name}:{node.lineno}:{node.id}")
            if isinstance(node, ast.Attribute) and node.attr in forbidden_identifiers:
                violations.append(f"acquisition.py:{method.name}:{node.lineno}:{node.attr}")
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and any(name in node.value.casefold() for name in ("prowlarr", "qbittorrent"))
            ):
                violations.append(f"acquisition.py:{method.name}:{node.lineno}:{node.value}")

    assert violations == []
