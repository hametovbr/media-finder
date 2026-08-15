"""Consumer-facing asynchronous control ports."""

from typing import Protocol

from .common import Locale, Page, PageRequest
from .manual import ManualDocumentV1
from .models import (
    AboutView,
    AcquisitionSubmissionRequest,
    AcquisitionView,
    BrowserSession,
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
    ReleaseSearchRequest,
    ReleaseSearchResult,
)


class ControlGateway(Protocol):
    async def list_collections(
        self, *, page: PageRequest, archived: bool
    ) -> Page[CollectionView]: ...

    async def create_collection(self, *, name: str) -> CollectionView: ...

    async def change_collection(self, *, collection_id: str, archived: bool) -> CollectionView: ...

    async def list_media_items(
        self,
        *,
        locale: Locale,
        page: PageRequest,
        collection_id: str | None,
        uncategorized: bool,
        archived: bool,
    ) -> Page[CatalogItemView]: ...

    async def get_media_item(self, *, item_id: str, locale: Locale) -> MediaItemDetail: ...

    async def change_media_item(
        self,
        *,
        item_id: str,
        collection_id: str | None,
        archived: bool | None,
        locale: Locale,
    ) -> MediaItemDetail: ...

    async def metadata_providers(self) -> tuple[MetadataProviderView, ...]: ...

    async def search_metadata(
        self, *, request: MetadataSearchRequest
    ) -> tuple[MetadataSearchResult, ...]: ...

    async def select_metadata(
        self, *, token: str, request: MetadataSelectionRequest, locale: Locale
    ) -> MediaItemDetail: ...

    async def import_manual(
        self, *, request: ManualImportRequest, confirmation_token: str | None = None
    ) -> ManualImportResult: ...

    async def edit_manual(
        self,
        *,
        item_id: str,
        document: ManualDocumentV1,
        confirmation_token: str | None = None,
    ) -> ManualImportResult: ...

    async def import_episodes(
        self, *, item_id: str, request: EpisodeImportRequest, locale: Locale
    ) -> MediaItemDetail: ...

    async def search_releases(
        self, *, item_id: str, request: ReleaseSearchRequest
    ) -> tuple[ReleaseSearchResult, ...]: ...

    async def list_destinations(self) -> tuple[DownloadDestination, ...]: ...

    async def submit_acquisition(
        self, *, request: AcquisitionSubmissionRequest
    ) -> AcquisitionView: ...

    async def reconcile_acquisition(self, *, acquisition_id: str) -> AcquisitionView: ...

    async def integration_diagnostics(self) -> tuple[IntegrationDiagnostic, ...]: ...

    async def about(self) -> AboutView: ...


class BrowserSecurityPort(Protocol):
    async def load_session(
        self, *, cookie: str | None, accept_language: str | None
    ) -> BrowserSession: ...

    async def serialize_session(self, *, session: BrowserSession) -> str: ...

    async def validate_csrf(self, *, session: BrowserSession, token: str | None) -> bool: ...
