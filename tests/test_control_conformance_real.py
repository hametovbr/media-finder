"""Stateful browser-control conformance against the real core facade and HTTP adapter."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from catalog_fixtures import CatalogFixture
from catalog_fixtures import RevisionInput as CatalogRevisionInput
from control_conformance import (
    ControlDriver,
    DirectControlDriver,
    DriverFailure,
    HttpControlDriver,
)
from fastapi.testclient import TestClient
from gateway_fixtures import create_gateway
from media_finder_core.acquisition import ReleaseSelectionCache, ReleaseSelectionService
from media_finder_core.acquisition.persistence import AcquisitionRecord
from media_finder_core.catalog.persistence import MediaItemRecord
from media_finder_core.platform import EphemeralCache
from media_finder_core.platform.database import create_database, migrate_to_head, session_factory
from media_finder_sdk import (
    CorrelationResult,
    DownloadArtifact,
    DownloadDestination,
    MagnetArtifact,
    MediaKind,
    MetadataIdentity,
    MetadataSearchQuery,
    MetadataSearchResult,
    ModuleError,
    ModuleFailureCategory,
    ModuleKind,
    ModuleManifest,
    NormalizedMetadata,
    PrivateReleaseSelection,
    Provenance,
    ProviderPayload,
    ReleaseCandidate,
    ReleaseSearchQuery,
    SafeReleaseSnapshot,
    SubmissionResult,
)
from media_finder_server.control_api import create_control_app
from media_finder_server.control_security import BackendBrowserSecurity
from pydantic import JsonValue


@dataclass(slots=True)
class FakeClock:
    current: datetime = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.current

    def advance(self, seconds: int = 10) -> None:
        self.current += timedelta(seconds=seconds)


class StatefulMetadataProvider:
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

    def __init__(self) -> None:
        self._values: dict[str, tuple[str, int | None, str]] = {}
        self._serial = 0

    def validate(self) -> None:
        return None

    def search(self, query: MetadataSearchQuery) -> tuple[MetadataSearchResult, ...]:
        self._serial += 1
        if query.query == "exact":
            external_id, title, year = "exact-1", "Exact title", 2024
        elif query.query == "similarity":
            external_id, title, year = "similarity-new", "Similar title", 2025
        else:
            external_id, title, year = f"search-{self._serial}", query.query, 2026
        self._values[external_id] = (title, year, query.locale)
        return (
            MetadataSearchResult(
                provider_id=self.manifest.module_id,
                external_id=external_id,
                media_kind=MediaKind.MOVIE,
                title=title,
                year=year,
                locale=query.locale,
            ),
        )

    def fetch(self, identity: MetadataIdentity) -> ProviderPayload:
        title, year, _locale = self._values[identity.external_id]
        return ProviderPayload(data={"title": title, "year": year})

    def normalize(
        self,
        payload: ProviderPayload,
        identity: MetadataIdentity,
    ) -> NormalizedMetadata:
        return NormalizedMetadata(
            kind=identity.media_kind,
            titles={identity.locale: str(payload.data["title"])},
            year=int(payload.data["year"]) if payload.data["year"] is not None else None,
            provenance=Provenance(
                provider_id=identity.provider_id,
                external_id=identity.external_id,
                locale=identity.locale,
            ),
        )

    def close(self) -> None:
        return None


class StatefulReleaseProvider:
    def __init__(self) -> None:
        self.disabled = False
        self.calls = 0
        self.resolve_error: ModuleError | None = None

    def validate(self) -> None:
        return None

    def search(self, query: ReleaseSearchQuery) -> tuple[ReleaseCandidate, ...]:
        if self.disabled:
            raise AssertionError("release_provider_used_during_reconcile")
        self.calls += 1
        return (
            ReleaseCandidate(
                snapshot=SafeReleaseSnapshot(
                    title=f"{query.query}.Release.{self.calls}",
                    indexer="Fixture Indexer",
                    guid=f"release-{self.calls}",
                ),
                selection=PrivateReleaseSelection.from_bytes(f"release-{self.calls}".encode()),
            ),
        )

    def resolve(self, selection: PrivateReleaseSelection) -> MagnetArtifact:
        if self.disabled:
            raise AssertionError("release_provider_used_during_reconcile")
        assert selection.payload().startswith(b"release-")
        if self.resolve_error is not None:
            raise self.resolve_error
        return MagnetArtifact(uri="magnet:?xt=urn:btih:0123456789012345678901234567890123456789")

    def close(self) -> None:
        return None


class StatefulDownloadClient:
    manifest = ModuleManifest(
        module_id="fixture-download",
        module_kind=ModuleKind.DOWNLOAD_CLIENT,
        module_version="9.8.7",
        sdk_compatibility=">=1,<2",
        contract_version="1",
        name_key="fixture.download",
        capabilities=frozenset({"destinations", "submit", "correlation", "magnet"}),
        translation_keys=frozenset({"fixture.download"}),
    )

    def __init__(self) -> None:
        self.destination = "current"
        self.tasks: dict[str, str] = {}
        self.submissions = 0
        self.submit_error: ModuleError | None = None

    def validate(self) -> None:
        return None

    def list_destinations(self) -> tuple[DownloadDestination, ...]:
        return (
            DownloadDestination(
                key=self.destination,
                label=self.destination.capitalize(),
            ),
        )

    def submit(
        self,
        artifact: DownloadArtifact,
        destination: str,
        correlation: str,
    ) -> SubmissionResult:
        del artifact
        self.submissions += 1
        if self.submit_error is not None:
            raise self.submit_error
        self.tasks[correlation] = destination
        return SubmissionResult(
            accepted=True,
            external_task_id=f"task-{self.submissions}",
            correlation=correlation,
        )

    def find_by_correlation(self, correlation: str) -> CorrelationResult:
        return CorrelationResult(
            found=correlation in self.tasks,
            correlation=correlation,
            external_task_id="reconciled" if correlation in self.tasks else None,
        )

    def close(self) -> None:
        return None


@dataclass(slots=True)
class RealControlState:
    clock: FakeClock
    gateway: object
    engine: object
    sessions: object
    provider: StatefulReleaseProvider
    client: StatefulDownloadClient
    catalog_item_id: str
    exact_item_id: str
    test_client: TestClient | None = None

    def pending_acquisition(self) -> str:
        identity = uuid4()
        correlation = f"mf-acq-{identity}"
        with self.sessions() as session:  # type: ignore[operator]
            item = session.get(MediaItemRecord, self.catalog_item_id)
            assert item is not None and item.current_revision_id is not None
            session.add(
                AcquisitionRecord(
                    id=identity,
                    correlation=correlation,
                    release_provider_id="fixture-release",
                    release_provider_version="1.2.3",
                    download_client_module_id="fixture-download",
                    download_client_module_version="9.8.7",
                    media_item_id=item.id,
                    metadata_revision_id=item.current_revision_id,
                    idempotency_key=f"pending-{identity}",
                    naming_profile="jellyfin-v1",
                    status="pending",
                    destination="current",
                    release_title="Pending.Release",
                    created_at=self.clock(),
                    updated_at=self.clock(),
                )
            )
            session.commit()
        self.client.tasks[correlation] = "current"
        return str(identity)

    def close(self) -> None:
        if self.test_client is not None:
            self.test_client.__exit__(None, None, None)
        self.gateway._test_release_selections.close()  # type: ignore[attr-defined,union-attr]
        self.gateway._test_runtime.close()  # type: ignore[attr-defined,union-attr]
        self.engine.dispose()  # type: ignore[union-attr]


def _metadata(*, provider: str, external_id: str, title: str, year: int) -> NormalizedMetadata:
    return NormalizedMetadata(
        kind=MediaKind.MOVIE,
        titles={"en": title},
        year=year,
        provenance=Provenance(
            provider_id=provider,
            external_id=external_id,
            locale="en",
        ),
    )


@pytest.fixture(params=("direct", "http"))
def real_control(request: pytest.FixtureRequest, tmp_path: Path):
    clock = FakeClock()
    url = f"sqlite:///{tmp_path / f'control-{request.param}.db'}"
    engine = create_database(url)
    migrate_to_head(url)
    sessions = session_factory(engine)
    metadata_provider = StatefulMetadataProvider()
    release_provider = StatefulReleaseProvider()
    client = StatefulDownloadClient()
    metadata_cache = EphemeralCache[MetadataSearchResult](
        ttl=timedelta(seconds=10), max_entries=2, clock=clock
    )
    manual_cache = EphemeralCache(ttl=timedelta(seconds=10), max_entries=2, clock=clock)
    releases = ReleaseSelectionService(
        provider=release_provider,
        cache=ReleaseSelectionCache(ttl=timedelta(seconds=10), max_entries=2, clock=clock),
    )
    with sessions() as session:
        catalog = CatalogFixture(session)
        exact, _ = catalog.get_or_create_item(
            metadata_provider.manifest.module_id,
            "exact-1",
            MediaKind.MOVIE,
        )
        catalog.add_revision(
            exact,
            CatalogRevisionInput.from_normalized(
                _metadata(
                    provider=metadata_provider.manifest.module_id,
                    external_id="exact-1",
                    title="Exact title",
                    year=2024,
                )
            ),
        )
        similar, _ = catalog.get_or_create_item("other-provider", "similar-1", MediaKind.MOVIE)
        catalog.add_revision(
            similar,
            CatalogRevisionInput.from_normalized(
                _metadata(
                    provider="other-provider",
                    external_id="similar-1",
                    title="Similar title",
                    year=2025,
                )
            ),
        )
        catalog_item, _ = catalog.get_or_create_item("manual", str(uuid4()), MediaKind.MOVIE)
        catalog.add_revision(
            catalog_item,
            CatalogRevisionInput.from_normalized(
                _metadata(
                    provider="manual",
                    external_id=catalog_item.external_id,
                    title="Acquisition title",
                    year=2026,
                )
            ),
        )
        gateway = create_gateway(
            session,
            metadata_provider=metadata_provider,
            release_selections=releases,
            download_client=client,
            metadata_selections=metadata_cache,
            manual_drafts=manual_cache,
        )
        catalog_item_id = catalog_item.id
        exact_item_id = exact.id
    state = RealControlState(
        clock=clock,
        gateway=gateway,
        engine=engine,
        sessions=sessions,
        provider=release_provider,
        client=client,
        catalog_item_id=catalog_item_id,
        exact_item_id=exact_item_id,
    )
    if request.param == "http":
        app = create_control_app(
            gateway=gateway,
            security=BackendBrowserSecurity(secret=b"real-control-session-secret-at-least-32"),
        )
        state.test_client = TestClient(app)
        state.test_client.__enter__()
        driver: ControlDriver = HttpControlDriver(state.test_client)
    else:
        driver = DirectControlDriver(gateway)
    try:
        yield driver, state
    finally:
        state.close()


def _failure(operation, *, code: str, status: int) -> DriverFailure:  # type: ignore[no-untyped-def]
    with pytest.raises(DriverFailure) as raised:
        operation()
    assert raised.value.code == code
    assert raised.value.status == status
    return raised.value


def _manual_document(
    *, external_id: str | None = None, title: str = "Manual series"
) -> dict[str, JsonValue]:
    return {
        "schema_version": "1",
        "external_id": external_id,
        "kind": "series",
        "locale": "en",
        "titles": {"en": title},
        "seasons": [
            {
                "number": 0,
                "episodes": [{"number": 1, "title": "Special"}],
            }
        ],
    }


def test_metadata_selection_contract(real_control) -> None:  # type: ignore[no-untyped-def]
    driver, state = real_control
    exact = driver.search_metadata("exact")[0]
    selected = driver.select_metadata(str(exact["token"]))
    assert selected.created is False
    assert selected.item["id"] == state.exact_item_id
    _failure(
        lambda: driver.select_metadata(str(exact["token"])),
        code="selection_expired",
        status=410,
    )

    similar = driver.search_metadata("similarity")[0]
    warning = _failure(
        lambda: driver.select_metadata(str(similar["token"])),
        code="confirmation_required",
        status=409,
    )
    confirmation = str(warning.details["confirmation_token"])
    assert driver.select_metadata(confirmation, confirm=True).created is True
    _failure(
        lambda: driver.select_metadata(confirmation, confirm=True),
        code="selection_expired",
        status=410,
    )


def test_metadata_tokens_expire_and_evict(real_control) -> None:  # type: ignore[no-untyped-def]
    driver, state = real_control
    expiring = driver.search_metadata("expiring")[0]
    state.clock.advance()
    _failure(
        lambda: driver.select_metadata(str(expiring["token"])),
        code="selection_expired",
        status=410,
    )

    first = driver.search_metadata("evict-first")[0]
    driver.search_metadata("evict-second")
    driver.search_metadata("evict-third")
    _failure(
        lambda: driver.select_metadata(str(first["token"])),
        code="selection_expired",
        status=410,
    )


def test_manual_edit_confirmation_csv_and_atomicity(real_control) -> None:  # type: ignore[no-untyped-def]
    driver, _state = real_control
    identity = str(uuid4())
    document = _manual_document(external_id=identity)
    created = driver.import_manual(document)
    item_id = str(created.item["id"])

    duplicate = _failure(
        lambda: driver.import_manual(_manual_document(external_id=identity, title="Updated")),
        code="confirmation_required",
        status=409,
    )
    token = str(duplicate.details["confirmation_token"])
    assert driver.confirm_manual(token).item["metadata"]["titles"] == {"en": "Updated"}  # type: ignore[index]
    _failure(lambda: driver.confirm_manual(token), code="selection_expired", status=410)

    edit = _failure(
        lambda: driver.edit_manual(
            item_id,
            _manual_document(external_id=identity, title="Edited"),
        ),
        code="confirmation_required",
        status=409,
    )
    edited = driver.confirm_manual(str(edit.details["confirmation_token"]))
    assert edited.item["metadata"]["titles"] == {"en": "Edited"}  # type: ignore[index]

    before = driver.get_item(item_id)
    _failure(
        lambda: driver.import_episodes(
            item_id,
            "season,episode,title\n1,1,Pilot\ninvalid,2,Broken\n",
        ),
        code="manual_import_invalid",
        status=422,
    )
    assert driver.get_item(item_id)["metadata"] == before["metadata"]
    imported = driver.import_episodes(item_id, "season,episode,title\n1,1,Pilot\n")
    assert imported["metadata"]["seasons"][-1]["episodes"][0]["title"] == "Pilot"  # type: ignore[index]


def test_manual_tokens_expire_and_evict(real_control) -> None:  # type: ignore[no-untyped-def]
    driver, state = real_control
    identity = str(uuid4())
    document = _manual_document(external_id=identity)
    driver.import_manual(document)
    expiring = _failure(
        lambda: driver.import_manual(document),
        code="confirmation_required",
        status=409,
    )
    state.clock.advance()
    _failure(
        lambda: driver.confirm_manual(str(expiring.details["confirmation_token"])),
        code="selection_expired",
        status=410,
    )

    tokens = [
        str(
            _failure(
                lambda: driver.import_manual(document),
                code="confirmation_required",
                status=409,
            ).details["confirmation_token"]
        )
        for _ in range(3)
    ]
    _failure(lambda: driver.confirm_manual(tokens[0]), code="selection_expired", status=410)


def test_release_tokens_destinations_idempotency_and_correlation(real_control) -> None:  # type: ignore[no-untyped-def]
    driver, state = real_control
    assert driver.destinations() == ({"key": "current", "label": "Current"},)
    release = driver.search_releases(state.catalog_item_id, "stale")[0]
    stale = _failure(
        lambda: driver.submit(
            item_id=state.catalog_item_id,
            release_token=str(release["token"]),
            destination="removed",
            idempotency_key="stale-attempt",
        ),
        code="download_destination_unavailable",
        status=409,
    )
    assert stale.details["destinations"] == [{"key": "current", "label": "Current"}]

    request = {
        "item_id": state.catalog_item_id,
        "release_token": str(release["token"]),
        "destination": "current",
        "idempotency_key": "successful-attempt",
    }
    first = driver.submit(**request)
    duplicate = driver.submit(**request)
    assert duplicate["id"] == first["id"]
    assert duplicate["status"] == "submitted"
    assert state.client.submissions == 1
    assert state.client.tasks == {f"mf-acq-{first['id']}": "current"}
    _failure(
        lambda: driver.submit(**(request | {"idempotency_key": "consumed-token-attempt"})),
        code="selection_expired",
        status=410,
    )


def test_release_tokens_expire_and_evict(real_control) -> None:  # type: ignore[no-untyped-def]
    driver, state = real_control
    expiring = driver.search_releases(state.catalog_item_id, "expiring")[0]
    state.clock.advance()
    _failure(
        lambda: driver.submit(
            item_id=state.catalog_item_id,
            release_token=str(expiring["token"]),
            destination="current",
            idempotency_key="expired-release",
        ),
        code="selection_expired",
        status=410,
    )

    first = driver.search_releases(state.catalog_item_id, "evict-first")[0]
    driver.search_releases(state.catalog_item_id, "evict-second")
    driver.search_releases(state.catalog_item_id, "evict-third")
    _failure(
        lambda: driver.submit(
            item_id=state.catalog_item_id,
            release_token=str(first["token"]),
            destination="current",
            idempotency_key="evicted-release",
        ),
        code="selection_expired",
        status=410,
    )


@pytest.mark.parametrize("failure_stage", ("resolve", "submit"))
def test_release_token_is_consumed_when_submission_fails_after_prechecks(
    real_control, failure_stage: str
) -> None:  # type: ignore[no-untyped-def]
    driver, state = real_control
    release = driver.search_releases(state.catalog_item_id, failure_stage)[0]
    failure_code = (
        "release_resolution_failed"
        if failure_stage == "resolve"
        else "download_client_submission_failed"
    )
    failure = ModuleError(
        category=ModuleFailureCategory.UNAVAILABLE,
        code=failure_code,
    )
    if failure_stage == "resolve":
        state.provider.resolve_error = failure
    else:
        state.client.submit_error = failure

    first = driver.submit(
        item_id=state.catalog_item_id,
        release_token=str(release["token"]),
        destination="current",
        idempotency_key=f"{failure_stage}-failure",
    )
    assert first["status"] == "failed"
    assert first["error_code"] == failure_code

    _failure(
        lambda: driver.submit(
            item_id=state.catalog_item_id,
            release_token=str(release["token"]),
            destination="current",
            idempotency_key=f"{failure_stage}-retry",
        ),
        code="selection_expired",
        status=410,
    )


def test_pending_reconcile_does_not_use_release_provider(real_control) -> None:  # type: ignore[no-untyped-def]
    driver, state = real_control
    acquisition_id = state.pending_acquisition()
    calls_before = state.provider.calls
    state.provider.disabled = True
    reconciled = driver.reconcile(acquisition_id)
    assert reconciled["status"] == "submitted"
    assert state.provider.calls == calls_before


def test_real_http_boundary_enforces_session_csrf_origin_and_no_cors(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'security.db'}"
    engine = create_database(url)
    migrate_to_head(url)
    sessions = session_factory(engine)
    with sessions() as session:
        gateway = create_gateway(session)
    app = create_control_app(
        gateway=gateway,
        security=BackendBrowserSecurity(secret=b"security-session-secret-at-least-32"),
    )
    try:
        with TestClient(app) as first, TestClient(app) as second:
            first_session = first.get("/v1/session")
            second_session = second.get("/v1/session")
            csrf = first_session.json()["csrf_token"]
            valid = {"Origin": "http://testserver", "X-CSRF-Token": csrf}

            missing = first.patch(
                "/v1/session", json={"ui_locale": "ru"}, headers={"Origin": "http://testserver"}
            )
            wrong = first.patch(
                "/v1/session",
                json={"ui_locale": "ru"},
                headers=valid | {"X-CSRF-Token": "wrong"},
            )
            replay = second.patch("/v1/session", json={"ui_locale": "ru"}, headers=valid)
            foreign = first.patch(
                "/v1/session",
                json={"ui_locale": "ru"},
                headers=valid | {"Origin": "https://attacker.example"},
            )
            for response, code in (
                (missing, "csrf_invalid"),
                (wrong, "csrf_invalid"),
                (replay, "csrf_invalid"),
                (foreign, "origin_invalid"),
            ):
                assert response.status_code == 403
                assert response.json()["error"]["code"] == code
                assert "access-control-allow-origin" not in response.headers
            assert first.get("/v1/session").json()["ui_locale"] == "en"

            first_success = first.patch("/v1/session", json={"ui_locale": "ru"}, headers=valid)
            second_success = first.patch(
                "/v1/session", json={"metadata_locale": "ru"}, headers=valid
            )
            assert first_success.status_code == second_success.status_code == 200
            assert second_success.json()["ui_locale"] == "ru"
            assert second_success.json()["metadata_locale"] == "ru"
            assert "access-control-allow-origin" not in first_success.headers

            preflight = first.options(
                "/v1/session",
                headers={
                    "Origin": "https://attacker.example",
                    "Access-Control-Request-Method": "PATCH",
                },
            )
            assert preflight.status_code == 405
            assert "access-control-allow-origin" not in preflight.headers
            assert second_session.json()["ui_locale"] == "en"
    finally:
        gateway._test_release_selections.close()  # type: ignore[attr-defined]
        gateway._test_runtime.close()  # type: ignore[attr-defined]
        engine.dispose()
