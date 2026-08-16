"""Portable browser-control orchestration for torrent acquisition."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from media_finder_control import AcquisitionStatus, ControlFailure
from media_finder_control.models import (
    AcquisitionSubmissionRequest,
    AcquisitionView,
    DownloadDestination,
    ReleaseSearchRequest,
    ReleaseSearchResult,
)
from media_finder_sdk import DownloadClient, ReleaseSearchFilter, ReleaseSearchQuery

from media_finder_core.acquisition.commands import AcquisitionCommands, ReleaseSelectionService
from media_finder_core.acquisition.models import (
    AcquisitionRequest,
    AcquisitionSnapshot,
    DestinationUnavailable,
    ModuleVersionSnapshot,
)
from media_finder_core.acquisition.ports import (
    AcquisitionQueryPort,
    AcquisitionUnitOfWork,
    PinnedCatalogReadPort,
)
from media_finder_core.catalog.ports import CatalogQueryPort
from media_finder_core.control.security import ControlPortError, invoke

__all__ = ["AcquisitionControlModules", "AcquisitionControlService"]

_ACQUISITION_CODES = {
    "acquisition_not_found",
    "acquisition_reference_not_found",
    "acquisition_unavailable",
    "download_client_correlation_mismatch",
    "download_client_module_mismatch",
    "download_client_unavailable",
    "media_item_not_found",
    "release_provider_unavailable",
    "release_search_failed",
    "release_search_token_expired",
}


class AcquisitionControlModules(Protocol):
    """Narrow module-runtime access needed by acquisition control."""

    def release_selections(self) -> ReleaseSelectionService: ...

    def download_client(self) -> DownloadClient: ...

    def release_module(self) -> ModuleVersionSnapshot: ...

    def download_module(self) -> ModuleVersionSnapshot: ...


class AcquisitionControlService:
    """Own release search, destinations, submission, and manual reconciliation."""

    def __init__(
        self,
        *,
        catalog_queries: CatalogQueryPort,
        pinned_catalog: PinnedCatalogReadPort,
        acquisition_queries: AcquisitionQueryPort,
        acquisition_uow: AcquisitionUnitOfWork,
        modules: AcquisitionControlModules,
        clock: Callable[[], datetime],
    ) -> None:
        self._catalog = catalog_queries
        self._pinned_catalog = pinned_catalog
        self._queries = acquisition_queries
        self._uow = acquisition_uow
        self._modules = modules
        self._clock = clock

    async def search_releases(
        self, *, item_id: str, request: ReleaseSearchRequest
    ) -> tuple[ReleaseSearchResult, ...]:
        return await invoke(
            lambda: self._search_releases(item_id=item_id, request=request),
            fallback="release_search_unavailable",
        )

    def _search_releases(
        self, *, item_id: str, request: ReleaseSearchRequest
    ) -> tuple[ReleaseSearchResult, ...]:
        item = self._catalog.get_item(item_id)
        if item is None or item.current_revision_id is None:
            raise ControlFailure(code="media_item_not_found", status=404)
        filters = (
            (
                ReleaseSearchFilter(
                    key="indexer-ids",
                    values=tuple(str(value) for value in request.indexer_ids),
                ),
            )
            if request.indexer_ids
            else ()
        )
        try:
            values = self._modules.release_selections().search(
                ReleaseSearchQuery(query=request.query, filters=filters)
            )
        except ControlPortError:
            raise
        except Exception as error:
            raise _acquisition_error(error, "release_search_failed") from None
        return tuple(
            ReleaseSearchResult(token=value.token, title=value.title, indexer=value.indexer)
            for value in values
        )

    async def list_destinations(self) -> tuple[DownloadDestination, ...]:
        return await invoke(self._list_destinations, fallback="download_client_unavailable")

    def _list_destinations(self) -> tuple[DownloadDestination, ...]:
        try:
            return tuple(
                DownloadDestination(key=value.key, label=value.label)
                for value in self._modules.download_client().list_destinations()
            )
        except ControlPortError:
            raise
        except Exception as error:
            raise _acquisition_error(error, "download_client_destinations_unavailable") from None

    async def submit_acquisition(self, *, request: AcquisitionSubmissionRequest) -> AcquisitionView:
        return await invoke(
            lambda: self._submit_acquisition(request), fallback="acquisition_unavailable"
        )

    def _submit_acquisition(self, request: AcquisitionSubmissionRequest) -> AcquisitionView:
        item = self._catalog.get_item(request.media_item_id)
        if item is None or item.current_revision_id is None:
            raise ControlFailure(code="media_item_not_found", status=404)
        try:
            command = AcquisitionCommands(
                query_port=self._queries,
                unit_of_work=self._uow,
                catalog=self._pinned_catalog,
                releases=self._modules.release_selections,
                download_client=self._modules.download_client,
                release_provider=self._modules.release_module(),
                download_client_module=self._modules.download_module,
                clock=self._clock,
            )
            value = command.submit(
                AcquisitionRequest(
                    media_item_id=item.id,
                    metadata_revision_id=item.current_revision_id,
                    destination=request.destination,
                    release_token=request.release_token,
                    idempotency_key=request.idempotency_key,
                    naming_profile="jellyfin-v1",
                )
            )
        except DestinationUnavailable as error:
            raise ControlFailure(
                code="download_destination_unavailable",
                status=409,
                details={
                    "destinations": [
                        {"key": value.key, "label": value.label}
                        for value in error.current_destinations
                    ]
                },
            ) from None
        except (ControlFailure, ControlPortError):
            raise
        except Exception as error:
            raise _acquisition_error(error, "acquisition_unavailable") from None
        return _acquisition_view(value)

    async def reconcile_acquisition(self, *, acquisition_id: str) -> AcquisitionView:
        return await invoke(
            lambda: self._reconcile_acquisition(acquisition_id),
            fallback="acquisition_unavailable",
        )

    def _reconcile_acquisition(self, acquisition_id: str) -> AcquisitionView:
        persisted = self._queries.get(acquisition_id)
        if persisted is None:
            raise ControlFailure(code="acquisition_not_found", status=404)
        selected = self._modules.download_module()
        if persisted.download_client.module_id != selected.module_id:
            raise ControlFailure(code="download_client_module_mismatch", status=422)
        try:
            value = AcquisitionCommands(
                query_port=self._queries,
                unit_of_work=self._uow,
                catalog=self._pinned_catalog,
                releases=None,
                download_client=self._modules.download_client,
                release_provider=persisted.release_provider,
                download_client_module=persisted.download_client,
                clock=self._clock,
            ).reconcile(acquisition_id)
        except (ControlFailure, ControlPortError):
            raise
        except Exception as error:
            raise _acquisition_error(error, "acquisition_unavailable") from None
        return _acquisition_view(value)


def _acquisition_error(error: Exception, fallback: str) -> ControlPortError:
    code = getattr(error, "code", None)
    if not isinstance(code, str) and isinstance(error, ValueError):
        code = str(error)
    return ControlPortError(code if code in _ACQUISITION_CODES else fallback)


def _acquisition_view(value: AcquisitionSnapshot) -> AcquisitionView:
    return AcquisitionView(
        id=str(value.id),
        media_item_id=value.media_item_id,
        status=AcquisitionStatus(value.status.value),
        release_title=value.release_snapshot.title,
        destination=value.destination,
        created_at=value.created_at,
        error_code=value.failure_code,
    )
