"""Small facade implementing the public asynchronous browser control gateway."""

from __future__ import annotations

from media_finder_control import Locale, Page, PageRequest
from media_finder_control.manual import ManualDocumentV1
from media_finder_control.models import (
    AboutView,
    AcquisitionSubmissionRequest,
    AcquisitionView,
    CatalogItemView,
    CollectionView,
    DownloadDestination,
    EpisodeImportRequest,
    IntegrationDiagnostic,
    ManualImportRequest,
    ManualImportResult,
    MediaItemDetail,
    MetadataProviderView,
    MetadataSearchRequest,
    MetadataSearchResult,
    MetadataSelectionRequest,
    MetadataSelectionResult,
    ReleaseSearchRequest,
    ReleaseSearchResult,
)

from media_finder_core.control.acquisition import AcquisitionControlService
from media_finder_core.control.catalog import CatalogControlService
from media_finder_core.control.diagnostics import DiagnosticsControlService
from media_finder_core.control.metadata import MetadataControlService

__all__ = ["ControlFacade"]


class ControlFacade:
    """Delegate every control operation to its owning bounded-context service."""

    def __init__(
        self,
        *,
        catalog: CatalogControlService,
        metadata: MetadataControlService,
        acquisition: AcquisitionControlService,
        diagnostics: DiagnosticsControlService,
    ) -> None:
        self._catalog = catalog
        self._metadata = metadata
        self._acquisition = acquisition
        self._diagnostics = diagnostics

    async def list_collections(self, *, page: PageRequest, archived: bool) -> Page[CollectionView]:
        return await self._catalog.list_collections(page=page, archived=archived)

    async def create_collection(self, *, name: str) -> CollectionView:
        return await self._catalog.create_collection(name=name)

    async def change_collection(self, *, collection_id: str, archived: bool) -> CollectionView:
        return await self._catalog.change_collection(collection_id=collection_id, archived=archived)

    async def list_media_items(
        self,
        *,
        locale: Locale,
        page: PageRequest,
        collection_id: str | None,
        uncategorized: bool,
        archived: bool,
    ) -> Page[CatalogItemView]:
        return await self._catalog.list_media_items(
            locale=locale,
            page=page,
            collection_id=collection_id,
            uncategorized=uncategorized,
            archived=archived,
        )

    async def get_media_item(self, *, item_id: str, locale: Locale) -> MediaItemDetail:
        return await self._catalog.get_media_item(item_id=item_id, locale=locale)

    async def change_media_item(
        self,
        *,
        item_id: str,
        collection_id: str | None,
        archived: bool | None,
        locale: Locale,
    ) -> MediaItemDetail:
        return await self._catalog.change_media_item(
            item_id=item_id,
            collection_id=collection_id,
            archived=archived,
            locale=locale,
        )

    async def metadata_providers(self) -> tuple[MetadataProviderView, ...]:
        return await self._metadata.metadata_providers()

    async def search_metadata(
        self, *, request: MetadataSearchRequest
    ) -> tuple[MetadataSearchResult, ...]:
        return await self._metadata.search_metadata(request=request)

    async def select_metadata(
        self, *, token: str, request: MetadataSelectionRequest, locale: Locale
    ) -> MetadataSelectionResult:
        return await self._metadata.select_metadata(token=token, request=request, locale=locale)

    async def import_manual(
        self, *, request: ManualImportRequest, confirmation_token: str | None = None
    ) -> ManualImportResult:
        return await self._metadata.import_manual(
            request=request, confirmation_token=confirmation_token
        )

    async def edit_manual(
        self,
        *,
        item_id: str,
        document: ManualDocumentV1,
        confirmation_token: str | None = None,
    ) -> ManualImportResult:
        return await self._metadata.edit_manual(
            item_id=item_id,
            document=document,
            confirmation_token=confirmation_token,
        )

    async def confirm_manual(self, *, token: str) -> ManualImportResult:
        return await self._metadata.confirm_manual(token=token)

    async def import_episodes(
        self, *, item_id: str, request: EpisodeImportRequest, locale: Locale
    ) -> MediaItemDetail:
        return await self._metadata.import_episodes(item_id=item_id, request=request, locale=locale)

    async def search_releases(
        self, *, item_id: str, request: ReleaseSearchRequest
    ) -> tuple[ReleaseSearchResult, ...]:
        return await self._acquisition.search_releases(item_id=item_id, request=request)

    async def list_destinations(self) -> tuple[DownloadDestination, ...]:
        return await self._acquisition.list_destinations()

    async def submit_acquisition(self, *, request: AcquisitionSubmissionRequest) -> AcquisitionView:
        return await self._acquisition.submit_acquisition(request=request)

    async def reconcile_acquisition(self, *, acquisition_id: str) -> AcquisitionView:
        return await self._acquisition.reconcile_acquisition(acquisition_id=acquisition_id)

    async def integration_diagnostics(self) -> tuple[IntegrationDiagnostic, ...]:
        return await self._diagnostics.integration_diagnostics()

    async def about(self) -> AboutView:
        return await self._diagnostics.about()
