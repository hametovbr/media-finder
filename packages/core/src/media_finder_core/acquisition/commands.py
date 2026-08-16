"""Acquisition orchestration and core-owned opaque release selections."""

from __future__ import annotations

import secrets
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import RLock
from uuid import UUID, uuid4

from media_finder_sdk import (
    CorrelationResult,
    DownloadArtifact,
    DownloadClient,
    DownloadDestination,
    MagnetArtifact,
    ModuleError,
    ModuleFailureCategory,
    PrivateReleaseSelection,
    ReleaseCandidate,
    ReleaseProvider,
    ReleaseSearchQuery,
    SafeReleaseSnapshot,
    SubmissionResult,
    TorrentArtifact,
)

from .models import (
    AcquisitionDraft,
    AcquisitionRequest,
    AcquisitionSnapshot,
    AcquisitionStatus,
    DestinationUnavailable,
    ModuleVersionSnapshot,
    safe_release_snapshot,
)
from .ports import AcquisitionQueryPort, AcquisitionUnitOfWork, PinnedCatalogReadPort


class ReleaseSelectionExpired(ValueError):
    def __init__(self) -> None:
        super().__init__("release_search_token_expired")


@dataclass(frozen=True, slots=True)
class SelectedRelease:
    token: str
    snapshot: SafeReleaseSnapshot

    @property
    def title(self) -> str:
        return self.snapshot.title

    @property
    def indexer(self) -> str:
        return self.snapshot.indexer


@dataclass(frozen=True, slots=True)
class ResolvedRelease:
    snapshot: SafeReleaseSnapshot
    artifact: DownloadArtifact


@dataclass(frozen=True, slots=True)
class _CacheEntry:
    candidate: ReleaseCandidate
    expires_at: datetime


class ReleaseSelectionCache:
    def __init__(
        self,
        *,
        ttl: timedelta = timedelta(minutes=10),
        max_entries: int = 512,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if ttl <= timedelta(0) or max_entries < 1:
            raise ValueError("release_selection_cache_bounds_invalid")
        self._ttl = ttl
        self._max_entries = max_entries
        self._clock = clock or (lambda: datetime.now(UTC))
        self._entries: OrderedDict[str, _CacheEntry] = OrderedDict()
        self._lock = RLock()

    def put(self, candidate: ReleaseCandidate) -> str:
        validated = _release_candidate(candidate)
        with self._lock:
            self._purge_expired()
            token = secrets.token_urlsafe(32)
            while token in self._entries:
                token = secrets.token_urlsafe(32)
            self._entries[token] = _CacheEntry(
                candidate=validated,
                expires_at=self._clock() + self._ttl,
            )
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)
            return token

    def get(self, token: str) -> ReleaseCandidate:
        with self._lock:
            entry = self._entries.get(token)
            if entry is None or entry.expires_at <= self._clock():
                self._entries.pop(token, None)
                raise ReleaseSelectionExpired
            self._entries.move_to_end(token)
            return entry.candidate

    def take(self, token: str) -> ReleaseCandidate:
        with self._lock:
            candidate = self.get(token)
            del self._entries[token]
            return candidate

    def _purge_expired(self) -> None:
        now = self._clock()
        for token in tuple(
            token for token, entry in self._entries.items() if entry.expires_at <= now
        ):
            del self._entries[token]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


class ReleaseSelectionService:
    def __init__(
        self,
        *,
        provider: ReleaseProvider | Callable[[], ReleaseProvider],
        cache: ReleaseSelectionCache,
    ) -> None:
        self._provider_source = provider
        self._cache = cache

    def _provider(self) -> ReleaseProvider:
        source = self._provider_source
        return source() if callable(source) else source

    def search(self, query: ReleaseSearchQuery) -> tuple[SelectedRelease, ...]:
        candidates = self._provider().search(query)
        if len(candidates) > query.limit:
            raise ModuleError(
                category=ModuleFailureCategory.LIMIT_EXCEEDED,
                code="release_result_limit_exceeded",
            )
        selected: list[SelectedRelease] = []
        for candidate in candidates:
            validated = _release_candidate(candidate)
            selected.append(
                SelectedRelease(
                    token=self._cache.put(validated),
                    snapshot=validated.snapshot,
                )
            )
        return tuple(selected)

    def inspect(self, token: str) -> SafeReleaseSnapshot:
        return self._cache.get(token).snapshot

    def resolve(self, token: str) -> ResolvedRelease:
        candidate = self._cache.take(token)
        return ResolvedRelease(
            snapshot=candidate.snapshot,
            artifact=_download_artifact(self._provider().resolve(candidate.selection)),
        )

    def close(self) -> None:
        self._cache.clear()


class AcquisitionCommands:
    def __init__(
        self,
        *,
        query_port: AcquisitionQueryPort,
        unit_of_work: AcquisitionUnitOfWork,
        catalog: PinnedCatalogReadPort,
        releases: ReleaseSelectionService | Callable[[], ReleaseSelectionService] | None,
        download_client: DownloadClient | Callable[[], DownloadClient],
        release_provider: ModuleVersionSnapshot,
        download_client_module: ModuleVersionSnapshot | Callable[[], ModuleVersionSnapshot],
        clock: Callable[[], datetime],
        uuid_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._queries = query_port
        self._uow = unit_of_work
        self._catalog = catalog
        self._releases_source = releases
        self._download_client_source = download_client
        self._release_provider = release_provider
        self._download_client_module_source = download_client_module
        self._clock = clock
        self._uuid_factory = uuid_factory

    def submit(self, request: AcquisitionRequest) -> AcquisitionSnapshot:
        existing = self._queries.find_by_idempotency(request.idempotency_key)
        if existing is not None:
            return existing
        if not self._catalog.has_pinned_revision(
            request.media_item_id, request.metadata_revision_id
        ):
            raise ValueError("acquisition_reference_not_found")

        client = self._download_client_capability()
        releases = self._release_selections()
        destinations = tuple(_download_destination(value) for value in client.list_destinations())
        if request.destination not in {value.key for value in destinations}:
            raise DestinationUnavailable(destinations)
        release_snapshot = _safe_release_snapshot(releases.inspect(request.release_token))
        acquisition_id = self._uuid_factory()
        correlation = f"mf-acq-{acquisition_id}"
        now = self._clock()
        draft = AcquisitionDraft(
            id=acquisition_id,
            media_item_id=request.media_item_id,
            metadata_revision_id=request.metadata_revision_id,
            idempotency_key=request.idempotency_key,
            naming_profile=request.naming_profile,
            destination=request.destination,
            correlation=correlation,
            release_snapshot=release_snapshot,
            release_provider=self._release_provider,
            download_client=self._download_client_module_snapshot(),
            created_at=now,
        )
        with self._uow.write() as repository:
            resolution = repository.create_pending_if_absent(draft)
            if not resolution.created:
                return resolution.acquisition
            acquisition = resolution.acquisition

        try:
            resolved = releases.resolve(request.release_token)
            result = _submission_result(
                client.submit(resolved.artifact, request.destination, correlation)
            )
        except ReleaseSelectionExpired:
            return self._transition(
                acquisition.id,
                status=AcquisitionStatus.FAILED,
                failure_code="release_search_token_expired",
            )
        except ModuleError as error:
            if error.code == "submission_timeout":
                return self._reconcile_lookup(
                    acquisition,
                    client=client,
                    absent_is_failure=True,
                )
            return self._transition(
                acquisition.id,
                status=AcquisitionStatus.FAILED,
                failure_code=_safe_code(error.code),
            )
        except Exception:
            return self._transition(
                acquisition.id,
                status=AcquisitionStatus.FAILED,
                failure_code="download_client_submission_failed",
            )

        if result.correlation != correlation:
            return self._transition(
                acquisition.id,
                status=AcquisitionStatus.FAILED,
                failure_code="download_client_correlation_mismatch",
            )
        if not result.accepted:
            return self._transition(
                acquisition.id,
                status=AcquisitionStatus.FAILED,
                failure_code="download_client_rejected",
            )
        return self._transition(
            acquisition.id,
            status=AcquisitionStatus.SUBMITTED,
            external_task_id=result.external_task_id,
        )

    def reconcile(self, acquisition_id: str) -> AcquisitionSnapshot:
        acquisition = self._queries.get(acquisition_id)
        if acquisition is None:
            raise ValueError("acquisition_not_found")
        if acquisition.status is not AcquisitionStatus.PENDING:
            return acquisition
        return self._reconcile_lookup(
            acquisition,
            client=self._download_client_capability(),
            absent_is_failure=False,
        )

    def _reconcile_lookup(
        self,
        acquisition: AcquisitionSnapshot,
        *,
        client: DownloadClient,
        absent_is_failure: bool,
    ) -> AcquisitionSnapshot:
        try:
            result = _correlation_result(client.find_by_correlation(acquisition.correlation))
        except Exception:
            return acquisition
        if result.correlation != acquisition.correlation or not result.conclusive:
            return acquisition
        if result.found:
            return self._transition(
                acquisition.id,
                status=AcquisitionStatus.SUBMITTED,
                external_task_id=result.external_task_id,
            )
        return self._transition(
            acquisition.id,
            status=AcquisitionStatus.FAILED,
            failure_code=(
                "submission_timeout_not_found"
                if absent_is_failure
                else "manual_reconcile_not_found"
            ),
        )

    def _release_selections(self) -> ReleaseSelectionService:
        source = self._releases_source
        if source is None:
            raise ValueError("acquisition_unavailable")
        return source() if callable(source) else source

    def _download_client_capability(self) -> DownloadClient:
        source = self._download_client_source
        return source() if callable(source) else source

    def _download_client_module_snapshot(self) -> ModuleVersionSnapshot:
        source = self._download_client_module_source
        return source() if callable(source) else source

    def _transition(
        self,
        acquisition_id: str,
        *,
        status: AcquisitionStatus,
        external_task_id: str | None = None,
        failure_code: str | None = None,
    ) -> AcquisitionSnapshot:
        with self._uow.write() as repository:
            return repository.transition(
                acquisition_id,
                expected_status=AcquisitionStatus.PENDING,
                status=status,
                external_task_id=external_task_id,
                failure_code=failure_code,
                updated_at=self._clock(),
            )


def _release_candidate(value: object) -> ReleaseCandidate:
    if not isinstance(value, ReleaseCandidate):
        raise ValueError("release_candidate_invalid")
    try:
        snapshot = _safe_release_snapshot(value.snapshot)
        selection = PrivateReleaseSelection.from_bytes(value.selection.payload())
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError("release_candidate_invalid") from error
    return ReleaseCandidate(snapshot=snapshot, selection=selection)


def _safe_release_snapshot(value: object) -> SafeReleaseSnapshot:
    if not isinstance(value, SafeReleaseSnapshot):
        raise ValueError("release_snapshot_invalid")
    try:
        payload = value.model_dump(mode="json")
        return safe_release_snapshot(SafeReleaseSnapshot.model_validate(payload))
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError("release_snapshot_invalid") from error


def _download_artifact(value: object) -> DownloadArtifact:
    try:
        if isinstance(value, MagnetArtifact):
            return MagnetArtifact.model_validate(value.model_dump(mode="json"))
        if isinstance(value, TorrentArtifact):
            return TorrentArtifact.from_bytes(value.content())
    except (TypeError, ValueError) as error:
        raise ValueError("release_artifact_invalid") from error
    raise ValueError("release_artifact_invalid")


def _download_destination(value: object) -> DownloadDestination:
    if not isinstance(value, DownloadDestination):
        raise ValueError("download_destination_invalid")
    try:
        return DownloadDestination.model_validate(value.model_dump(mode="json"))
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError("download_destination_invalid") from error


def _submission_result(value: object) -> SubmissionResult:
    if not isinstance(value, SubmissionResult):
        raise ValueError("download_client_submission_invalid")
    try:
        result = SubmissionResult.model_validate(value.model_dump(mode="json"))
        _validate_external_task_id(result.external_task_id)
        return result
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError("download_client_submission_invalid") from error


def _correlation_result(value: object) -> CorrelationResult:
    if not isinstance(value, CorrelationResult):
        raise ValueError("download_client_correlation_invalid")
    try:
        result = CorrelationResult.model_validate(value.model_dump(mode="json"))
        _validate_external_task_id(result.external_task_id)
        return result
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError("download_client_correlation_invalid") from error


def _safe_code(code: str) -> str:
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789_-")
    if not code or len(code) > 200 or any(character not in allowed for character in code):
        return "download_client_submission_failed"
    return code


def _validate_external_task_id(value: str | None) -> None:
    if value is not None and (len(value) > 500 or any(ord(character) < 32 for character in value)):
        raise ValueError("download_client_submission_invalid")


__all__ = [
    "AcquisitionCommands",
    "ReleaseSelectionCache",
    "ReleaseSelectionExpired",
    "ReleaseSelectionService",
    "ResolvedRelease",
    "SelectedRelease",
]
