"""Focused application contract for the acquisition bounded context."""

from __future__ import annotations

import ast
import importlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, fields, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
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

NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)
ROOT = Path(__file__).parents[3]
ACQUISITION_ROOT = ROOT / "packages" / "core" / "src" / "media_finder_core" / "acquisition"
FIRST_UUID = UUID("11111111-1111-4111-8111-111111111111")
SECOND_UUID = UUID("22222222-2222-4222-8222-222222222222")


def _api() -> SimpleNamespace:
    try:
        modules = {
            name: importlib.import_module(f"media_finder_core.acquisition.{name}")
            for name in ("models", "ports", "commands", "queries")
        }
    except ModuleNotFoundError as error:
        pytest.fail(f"acquisition bounded context is missing: {error.name}")
    required = {
        "AcquisitionStatus": getattr(modules["models"], "AcquisitionStatus", None),
        "ModuleVersionSnapshot": getattr(modules["models"], "ModuleVersionSnapshot", None),
        "AcquisitionRequest": getattr(modules["models"], "AcquisitionRequest", None),
        "AcquisitionDraft": getattr(modules["models"], "AcquisitionDraft", None),
        "AcquisitionSnapshot": getattr(modules["models"], "AcquisitionSnapshot", None),
        "DestinationUnavailable": getattr(modules["models"], "DestinationUnavailable", None),
        "AcquisitionRepository": getattr(modules["ports"], "AcquisitionRepository", None),
        "AcquisitionQueryPort": getattr(modules["ports"], "AcquisitionQueryPort", None),
        "AcquisitionUnitOfWork": getattr(modules["ports"], "AcquisitionUnitOfWork", None),
        "PinnedCatalogReadPort": getattr(modules["ports"], "PinnedCatalogReadPort", None),
        "ReleaseSelectionCache": getattr(modules["commands"], "ReleaseSelectionCache", None),
        "ReleaseSelectionExpired": getattr(modules["commands"], "ReleaseSelectionExpired", None),
        "ReleaseSelectionService": getattr(modules["commands"], "ReleaseSelectionService", None),
        "AcquisitionCommands": getattr(modules["commands"], "AcquisitionCommands", None),
        "AcquisitionQueries": getattr(modules["queries"], "AcquisitionQueries", None),
    }
    missing = sorted(name for name, value in required.items() if value is None)
    assert missing == [], f"acquisition public application types are missing: {missing}"
    return SimpleNamespace(**required, **modules)


def _release_snapshot(title: str = "Fixture.Release.2026") -> SafeReleaseSnapshot:
    return SafeReleaseSnapshot(
        title=title,
        indexer="Fixture Indexer",
        guid="fixture:release-1",
        infohash="a" * 40,
        source_page_url="https://indexer.example/releases/1",
    )


def _candidate(title: str = "Fixture.Release.2026") -> ReleaseCandidate:
    return ReleaseCandidate(
        snapshot=_release_snapshot(title),
        selection=PrivateReleaseSelection.from_bytes(f"private:{title}".encode()),
    )


class _ReleaseProvider:
    def __init__(self, candidates: tuple[ReleaseCandidate, ...] | None = None) -> None:
        self.candidates = candidates or (_candidate(),)
        self.resolve_calls = 0
        self.resolve_error: BaseException | None = None

    def validate(self) -> None: ...

    def search(self, query: ReleaseSearchQuery) -> tuple[ReleaseCandidate, ...]:
        assert query.query
        return self.candidates

    def resolve(self, selection: PrivateReleaseSelection) -> MagnetArtifact:
        self.resolve_calls += 1
        assert selection.payload().startswith(b"private:")
        if self.resolve_error is not None:
            raise self.resolve_error
        return MagnetArtifact(uri=f"magnet:?xt=urn:btih:{'a' * 40}")

    def close(self) -> None: ...


class _CatalogReadPort:
    def __init__(self) -> None:
        self.valid = True
        self.calls: list[tuple[str, str]] = []

    def has_pinned_revision(self, media_item_id: str, metadata_revision_id: str) -> bool:
        self.calls.append((media_item_id, metadata_revision_id))
        return self.valid


class _MemoryAcquisitions:
    def __init__(self, api: SimpleNamespace) -> None:
        self.api = api
        self.values: dict[str, Any] = {}

    def snapshot(self) -> dict[str, Any]:
        return dict(self.values)

    def restore(self, state: dict[str, Any]) -> None:
        self.values = state

    def find_by_idempotency(self, key: str):
        return next(
            (value for value in self.values.values() if value.idempotency_key == key),
            None,
        )

    def get(self, acquisition_id: str):
        return self.values.get(acquisition_id)

    def add_pending(self, draft: Any):
        value = self.api.AcquisitionSnapshot(
            id=str(draft.id),
            media_item_id=draft.media_item_id,
            metadata_revision_id=draft.metadata_revision_id,
            idempotency_key=draft.idempotency_key,
            naming_profile=draft.naming_profile,
            status=self.api.AcquisitionStatus.PENDING,
            destination=draft.destination,
            correlation=draft.correlation,
            release_snapshot=draft.release_snapshot,
            release_provider=draft.release_provider,
            download_client=draft.download_client,
            external_task_id=None,
            failure_code=None,
            created_at=draft.created_at,
            updated_at=draft.created_at,
        )
        self.values[value.id] = value
        return value

    def create_pending_if_absent(self, draft: Any):
        existing = self.find_by_idempotency(draft.idempotency_key)
        if existing is not None:
            return SimpleNamespace(acquisition=existing, created=False)
        return SimpleNamespace(acquisition=self.add_pending(draft), created=True)

    def transition(
        self,
        acquisition_id: str,
        *,
        expected_status: Any,
        status: Any,
        external_task_id: str | None,
        failure_code: str | None,
        updated_at: datetime,
    ):
        current = self.values[acquisition_id]
        if current.status is not expected_status:
            raise ValueError("acquisition_state_changed")
        updated = replace(
            current,
            status=status,
            external_task_id=external_task_id,
            failure_code=failure_code,
            updated_at=updated_at,
        )
        self.values[acquisition_id] = updated
        return updated

    def pending(self):
        return tuple(
            sorted(
                (
                    value
                    for value in self.values.values()
                    if value.status is self.api.AcquisitionStatus.PENDING
                ),
                key=lambda value: (value.created_at, value.id),
            )
        )

    def for_media_item(self, media_item_id: str, *, limit: int):
        return tuple(
            sorted(
                (value for value in self.values.values() if value.media_item_id == media_item_id),
                key=lambda value: (value.created_at, value.id),
                reverse=True,
            )[:limit]
        )


class _UnitOfWork:
    def __init__(self, store: _MemoryAcquisitions) -> None:
        self.store = store
        self.active = False
        self.writes = 0
        self.rollbacks = 0
        self.on_next_write: Callable[[], None] | None = None

    @contextmanager
    def write(self) -> Iterator[_MemoryAcquisitions]:
        if self.on_next_write is not None:
            callback, self.on_next_write = self.on_next_write, None
            callback()
        before = self.store.snapshot()
        self.active = True
        self.writes += 1
        try:
            yield self.store
        except BaseException:
            self.store.restore(before)
            self.rollbacks += 1
            raise
        finally:
            self.active = False


class _DownloadClient:
    def __init__(self, store: _MemoryAcquisitions, uow: _UnitOfWork) -> None:
        self.store = store
        self.uow = uow
        self.destinations = (DownloadDestination(key="anime", label="Anime"),)
        self.submissions: list[tuple[str, str]] = []
        self.submission_result: SubmissionResult | None = None
        self.submission_error: BaseException | None = None
        self.lookup_result: CorrelationResult | None = None
        self.lookup_calls: list[str] = []

    def validate(self) -> None: ...

    def list_destinations(self) -> tuple[DownloadDestination, ...]:
        assert self.uow.active is False
        return self.destinations

    def submit(self, artifact: Any, destination: str, correlation: str) -> SubmissionResult:
        assert self.uow.active is False
        assert isinstance(artifact, MagnetArtifact)
        pending = self.store.get(correlation.removeprefix("mf-acq-"))
        assert pending is not None and pending.status.value == "pending"
        self.submissions.append((destination, correlation))
        if self.submission_error is not None:
            raise self.submission_error
        return self.submission_result or SubmissionResult(
            accepted=True,
            external_task_id="client-task-1",
            correlation=correlation,
        )

    def find_by_correlation(self, correlation: str) -> CorrelationResult:
        assert self.uow.active is False
        self.lookup_calls.append(correlation)
        return self.lookup_result or CorrelationResult(found=False, correlation=correlation)

    def close(self) -> None: ...


def _services(
    *,
    uuids: tuple[UUID, ...] = (FIRST_UUID, SECOND_UUID),
) -> SimpleNamespace:
    api = _api()
    store = _MemoryAcquisitions(api)
    uow = _UnitOfWork(store)
    catalog = _CatalogReadPort()
    provider = _ReleaseProvider()
    cache = api.ReleaseSelectionCache(ttl=timedelta(minutes=10), max_entries=8, clock=lambda: NOW)
    releases = api.ReleaseSelectionService(provider=provider, cache=cache)
    client = _DownloadClient(store, uow)
    sequence = iter(uuids)
    commands = api.AcquisitionCommands(
        query_port=store,
        unit_of_work=uow,
        catalog=catalog,
        releases=releases,
        download_client=client,
        release_provider=api.ModuleVersionSnapshot(
            module_id="release-provider", module_version="1.2.3"
        ),
        download_client_module=api.ModuleVersionSnapshot(
            module_id="download-client", module_version="4.5.6"
        ),
        clock=lambda: NOW,
        uuid_factory=lambda: next(sequence),
    )
    queries = api.AcquisitionQueries(query_port=store)
    return SimpleNamespace(
        api=api,
        store=store,
        uow=uow,
        catalog=catalog,
        provider=provider,
        releases=releases,
        client=client,
        commands=commands,
        queries=queries,
    )


def _token(context: SimpleNamespace, title: str = "Fixture.Release.2026") -> str:
    context.provider.candidates = (_candidate(title),)
    return context.releases.search(ReleaseSearchQuery(query="Fixture"))[0].token


def _request(token: str, *, idempotency_key: str = "form-1") -> Any:
    api = _api()
    return api.AcquisitionRequest(
        media_item_id="item-1",
        metadata_revision_id="revision-1",
        destination="anime",
        release_token=token,
        idempotency_key=idempotency_key,
        naming_profile="jellyfin-v1",
    )


def test_acquisition_values_are_immutable_and_states_are_bounded() -> None:
    context = _services()
    assert (
        context.api.ModuleVersionSnapshot("vendor.release_provider", "1.2.3").module_id
        == "vendor.release_provider"
    )
    assert (
        context.api.ModuleVersionSnapshot("vendor_download.client", "1.2.3").module_id
        == "vendor_download.client"
    )
    token = _token(context)
    acquisition = context.commands.submit(_request(token))

    assert {status.value for status in context.api.AcquisitionStatus} == {
        "pending",
        "submitted",
        "failed",
    }
    assert acquisition.status is context.api.AcquisitionStatus.SUBMITTED
    with pytest.raises((FrozenInstanceError, AttributeError)):
        acquisition.metadata_revision_id = "other"


def test_submit_persists_pending_first_pins_catalog_and_is_idempotent() -> None:
    context = _services()
    token = _token(context)
    request = _request(token)

    first = context.commands.submit(request)
    duplicate = context.commands.submit(replace(request, release_token="expired-token"))

    assert duplicate == first
    assert first.id == str(FIRST_UUID)
    assert first.metadata_revision_id == "revision-1"
    assert first.correlation == f"mf-acq-{FIRST_UUID}"
    assert first.destination == "anime"
    assert first.release_snapshot == _release_snapshot()
    assert (first.release_provider.module_id, first.release_provider.module_version) == (
        "release-provider",
        "1.2.3",
    )
    assert (first.download_client.module_id, first.download_client.module_version) == (
        "download-client",
        "4.5.6",
    )
    assert context.catalog.calls == [("item-1", "revision-1")]
    assert context.client.submissions == [("anime", f"mf-acq-{FIRST_UUID}")]
    assert context.provider.resolve_calls == 1


def test_invalid_pinned_catalog_reference_has_no_acquisition_or_external_effect() -> None:
    context = _services()
    context.catalog.valid = False
    token = _token(context)

    with pytest.raises(ValueError, match="acquisition_reference_not_found"):
        context.commands.submit(_request(token))

    assert context.store.values == {}
    assert context.client.submissions == []
    assert context.provider.resolve_calls == 0
    assert context.releases.inspect(token) == _release_snapshot()


def test_safe_snapshot_is_persisted_without_private_selection_or_artifact() -> None:
    context = _services()
    acquisition = context.commands.submit(_request(_token(context)))

    field_names = {field.name for field in fields(acquisition)}
    assert acquisition.release_snapshot.model_dump(mode="json") == {
        "title": "Fixture.Release.2026",
        "indexer": "Fixture Indexer",
        "guid": "fixture:release-1",
        "infohash": "a" * 40,
        "source_page_url": "https://indexer.example/releases/1",
    }
    assert field_names.isdisjoint(
        {"artifact", "magnet", "torrent", "private_selection", "download_url"}
    )
    assert "private:Fixture" not in repr(acquisition)


def test_atomic_idempotency_recheck_returns_racing_attempt_without_consuming_token() -> None:
    context = _services()
    token = _token(context)

    def concurrent_insert() -> None:
        draft = context.api.AcquisitionDraft(
            id=SECOND_UUID,
            media_item_id="item-1",
            metadata_revision_id="revision-1",
            idempotency_key="form-1",
            naming_profile="jellyfin-v1",
            destination="anime",
            correlation=f"mf-acq-{SECOND_UUID}",
            release_snapshot=_release_snapshot("Concurrent"),
            release_provider=context.api.ModuleVersionSnapshot(
                module_id="release-provider", module_version="1.2.3"
            ),
            download_client=context.api.ModuleVersionSnapshot(
                module_id="download-client", module_version="4.5.6"
            ),
            created_at=NOW,
        )
        context.store.add_pending(draft)

    context.uow.on_next_write = concurrent_insert
    result = context.commands.submit(_request(token))

    assert result.id == str(SECOND_UUID)
    assert context.client.submissions == []
    assert context.provider.resolve_calls == 0
    assert context.releases.inspect(token) == _release_snapshot()


def test_client_correlation_mismatch_fails_without_accepting_foreign_task() -> None:
    context = _services()
    context.client.submission_result = SubmissionResult(
        accepted=True,
        external_task_id="foreign-task",
        correlation="mf-acq-00000000-0000-4000-8000-000000000000",
    )

    result = context.commands.submit(_request(_token(context)))

    assert result.status is context.api.AcquisitionStatus.FAILED
    assert result.failure_code == "download_client_correlation_mismatch"
    assert result.external_task_id is None


def test_invalid_external_task_output_fails_without_persisting_unsafe_value() -> None:
    context = _services()
    context.client.submission_result = SubmissionResult(
        accepted=True,
        external_task_id="unsafe\nidentifier",
        correlation=f"mf-acq-{FIRST_UUID}",
    )

    result = context.commands.submit(_request(_token(context)))

    assert result.status is context.api.AcquisitionStatus.FAILED
    assert result.failure_code == "download_client_submission_failed"
    assert result.external_task_id is None


@pytest.mark.parametrize(
    ("lookup", "expected_status", "expected_failure"),
    [
        ("found", "submitted", None),
        ("absent", "failed", "submission_timeout_not_found"),
        ("inconclusive", "pending", None),
    ],
)
def test_timeout_recovers_by_exact_lookup_without_resubmission(
    lookup: str,
    expected_status: str,
    expected_failure: str | None,
) -> None:
    context = _services()
    context.client.submission_error = ModuleError(
        category=ModuleFailureCategory.TIMEOUT,
        code="submission_timeout",
    )
    context.client.lookup_result = CorrelationResult(
        found=lookup == "found",
        correlation=f"mf-acq-{FIRST_UUID}",
        external_task_id="accepted-before-timeout" if lookup == "found" else None,
        conclusive=lookup != "inconclusive",
    )

    result = context.commands.submit(_request(_token(context)))

    assert result.status.value == expected_status
    assert result.failure_code == expected_failure
    assert context.client.submissions == [("anime", f"mf-acq-{FIRST_UUID}")]
    assert context.client.lookup_calls == [f"mf-acq-{FIRST_UUID}"]


def test_restart_lists_pending_without_submission_and_manual_reconcile_is_explicit() -> None:
    context = _services()
    context.client.submission_error = ModuleError(
        category=ModuleFailureCategory.TIMEOUT,
        code="submission_timeout",
    )
    context.client.lookup_result = CorrelationResult(
        found=False,
        correlation=f"mf-acq-{FIRST_UUID}",
        conclusive=False,
    )
    pending = context.commands.submit(_request(_token(context)))
    submission_count = len(context.client.submissions)

    assert context.queries.pending_after_startup() == (pending,)
    assert len(context.client.submissions) == submission_count

    context.client.lookup_result = CorrelationResult(
        found=True,
        correlation=pending.correlation,
        external_task_id="reconciled-task",
    )
    reconciled = context.commands.reconcile(pending.id)
    assert reconciled.status is context.api.AcquisitionStatus.SUBMITTED
    assert reconciled.external_task_id == "reconciled-task"
    assert len(context.client.submissions) == submission_count
    assert context.commands.reconcile(pending.id) == reconciled
    assert context.client.lookup_calls.count(pending.correlation) == 2


def test_release_selection_is_bounded_ttl_opaque_and_one_use_even_on_failure() -> None:
    api = _api()
    now = [NOW]
    provider = _ReleaseProvider()
    cache = api.ReleaseSelectionCache(
        ttl=timedelta(seconds=10), max_entries=2, clock=lambda: now[0]
    )
    service = api.ReleaseSelectionService(provider=provider, cache=cache)

    first = service.search(ReleaseSearchQuery(query="First"))[0]
    provider.candidates = (_candidate("Second"),)
    second = service.search(ReleaseSearchQuery(query="Second"))[0]
    provider.candidates = (_candidate("Third"),)
    third = service.search(ReleaseSearchQuery(query="Third"))[0]

    assert len({first.token, second.token, third.token}) == 3
    assert "private:" not in first.token
    with pytest.raises(api.ReleaseSelectionExpired):
        service.inspect(first.token)

    resolved = service.resolve(second.token)
    assert isinstance(resolved.artifact, MagnetArtifact)
    with pytest.raises(api.ReleaseSelectionExpired):
        service.resolve(second.token)

    provider.resolve_error = ModuleError(
        category=ModuleFailureCategory.LIMIT_EXCEEDED,
        code="release_torrent_too_large",
    )
    with pytest.raises(ModuleError, match="release_torrent_too_large"):
        service.resolve(third.token)
    with pytest.raises(api.ReleaseSelectionExpired):
        service.inspect(third.token)

    expiring = service.search(ReleaseSearchQuery(query="Expiring"))[0]
    now[0] += timedelta(seconds=10)
    with pytest.raises(api.ReleaseSelectionExpired, match="release_search_token_expired"):
        service.inspect(expiring.token)


def test_release_selection_sanitizes_snapshot_and_enforces_the_query_result_limit() -> None:
    api = _api()
    unsafe = ReleaseCandidate(
        snapshot=SafeReleaseSnapshot(
            title="Unsafe.Release",
            indexer="Fixture Indexer",
            guid="https://secret.example/path",
            infohash="A" * 40,
            source_page_url="https://user:password@indexer.example/release?passkey=secret",
        ),
        selection=PrivateReleaseSelection.from_bytes(b"private:unsafe"),
    )
    provider = _ReleaseProvider((unsafe,))
    service = api.ReleaseSelectionService(
        provider=provider,
        cache=api.ReleaseSelectionCache(),
    )

    selected = service.search(ReleaseSearchQuery(query="Unsafe"))[0]

    assert selected.snapshot.guid is None
    assert selected.snapshot.infohash == "a" * 40
    assert selected.snapshot.source_page_url is None

    provider.candidates = (unsafe, unsafe)
    with pytest.raises(ModuleError, match="release_result_limit_exceeded"):
        service.search(ReleaseSearchQuery(query="Too many", limit=1))


def test_acquisition_ports_are_explicit_and_application_files_are_framework_free() -> None:
    api = _api()
    assert all(
        getattr(port, "_is_protocol", False)
        for port in (
            api.AcquisitionRepository,
            api.AcquisitionQueryPort,
            api.AcquisitionUnitOfWork,
            api.PinnedCatalogReadPort,
        )
    )

    violations: list[str] = []
    for name in ("models.py", "ports.py", "commands.py", "queries.py"):
        path = ACQUISITION_ROOT / name
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            else:
                modules = []
            violations.extend(
                f"{name}:{node.lineno}:{module}"
                for module in modules
                if module == "sqlalchemy"
                or module.startswith("sqlalchemy.")
                or module == "fastapi"
                or module.startswith("fastapi.")
                or module.endswith(".persistence")
                or module
                in {
                    "media_finder_core.catalog.models",
                    "media_finder_core.catalog.persistence",
                }
            )
    assert violations == []
