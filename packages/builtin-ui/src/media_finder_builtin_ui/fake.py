"""Deterministic in-memory control gateway for UI development and tests."""

from datetime import UTC, datetime

from media_finder_control import (
    AcquisitionStatus,
    Locale,
    MediaKind,
    Page,
    PageRequest,
    ReadinessStatus,
)
from media_finder_control.manual import EpisodeDocument, ManualDocumentV1, SeasonDocument
from media_finder_control.models import (
    AboutView,
    AcquisitionSubmissionRequest,
    AcquisitionView,
    AttributionView,
    CatalogItemView,
    CollectionView,
    DownloadDestination,
    EpisodeImportRequest,
    IntegrationDiagnostic,
    IntegrationVariableView,
    ManualImportRequest,
    ManualImportResult,
    MediaItemDetail,
    MetadataProviderView,
    MetadataSearchRequest,
    MetadataSearchResult,
    MetadataSelectionRequest,
    MetadataView,
    ReleaseSearchRequest,
    ReleaseSearchResult,
)

RU_EXAMPLE = "\u041f\u0440\u0438\u043c\u0435\u0440"
RU_MOVIE = f"{RU_EXAMPLE} \u0444\u0438\u043b\u044c\u043c\u0430"
RU_SERIES = f"{RU_EXAMPLE} \u0441\u0435\u0440\u0438\u0430\u043b\u0430"


class FakeControlGateway:
    """Stable fixture implementation with no persistence or network access."""

    def __init__(self) -> None:
        self._acquisitions: dict[str, AcquisitionView] = {}

    async def list_collections(self, *, page: PageRequest, archived: bool) -> Page[CollectionView]:
        del page
        items = (
            (CollectionView(id="collection-1", name="Examples", archived=False),)
            if not archived
            else (CollectionView(id="collection-old", name="Archive", archived=True),)
        )
        return Page(items=items)

    async def create_collection(self, *, name: str) -> CollectionView:
        return CollectionView(id="collection-created", name=name)

    async def change_collection(self, *, collection_id: str, archived: bool) -> CollectionView:
        return CollectionView(id=collection_id, name="Examples", archived=archived)

    async def list_media_items(
        self,
        *,
        locale: Locale,
        page: PageRequest,
        collection_id: str | None,
        uncategorized: bool,
        archived: bool,
    ) -> Page[CatalogItemView]:
        del page, collection_id, uncategorized
        titles = {
            Locale.EN: ("Example Movie", "Example Series"),
            Locale.RU: (RU_MOVIE, RU_SERIES),
        }
        movie, series = titles[locale]
        return Page(
            items=(
                CatalogItemView(
                    id="movie-1",
                    title=movie,
                    year=2024,
                    kind=MediaKind.MOVIE,
                    provider_key="manual",
                    latest_acquisition_status=AcquisitionStatus.SUBMITTED,
                    archived=archived,
                ),
                CatalogItemView(
                    id="series-1",
                    title=series,
                    year=2025,
                    kind=MediaKind.SERIES,
                    provider_key="tmdb",
                    latest_acquisition_status=AcquisitionStatus.FAILED,
                    archived=archived,
                ),
            )
        )

    async def get_media_item(self, *, item_id: str, locale: Locale) -> MediaItemDetail:
        if item_id == "series-1":
            titles = {
                "en": "Example Series",
                "ru": RU_SERIES,
            }
            metadata = MetadataView(
                kind=MediaKind.SERIES,
                titles=titles,
                year=2025,
                seasons=(
                    SeasonDocument(
                        number=0,
                        title="Specials",
                        episodes=(EpisodeDocument(number=1, title="Special"),),
                    ),
                    SeasonDocument(
                        number=1,
                        title="Season 1",
                        episodes=(EpisodeDocument(number=1, title="Pilot"),),
                    ),
                ),
            )
            provider = "tmdb"
            external_id = "100"
        else:
            titles = {
                "en": "Example Movie",
                "ru": RU_MOVIE,
            }
            metadata = MetadataView(kind=MediaKind.MOVIE, titles=titles, year=2024)
            provider = "manual"
            external_id = "e0a465bb-34eb-4565-bde2-b80d6e789b7c"
        del locale
        acquisitions = tuple(
            acquisition
            for acquisition in self._acquisitions.values()
            if acquisition.id.startswith(item_id)
        )
        return MediaItemDetail(
            id=item_id,
            provider_key=provider,
            external_id=external_id,
            kind=metadata.kind,
            metadata=metadata,
            acquisitions=acquisitions,
        )

    async def change_media_item(
        self,
        *,
        item_id: str,
        collection_id: str | None,
        archived: bool | None,
        locale: Locale,
    ) -> MediaItemDetail:
        item = await self.get_media_item(item_id=item_id, locale=locale)
        return item.model_copy(
            update={
                "collection_id": collection_id,
                "archived": item.archived if archived is None else archived,
            }
        )

    async def metadata_providers(self) -> tuple[MetadataProviderView, ...]:
        return (
            MetadataProviderView(
                key="manual",
                name_key="module.manual.name",
                capabilities=frozenset({"movie", "series"}),
                ready=True,
            ),
            MetadataProviderView(
                key="tmdb",
                name_key="module.tmdb.name",
                capabilities=frozenset({"movie", "series"}),
                ready=False,
            ),
        )

    async def search_metadata(
        self, *, request: MetadataSearchRequest
    ) -> tuple[MetadataSearchResult, ...]:
        token = "metadata-duplicate" if "duplicate" in request.query.casefold() else "metadata-1"
        return (
            MetadataSearchResult(
                token=token,
                provider_key="tmdb",
                external_id="100",
                kind=MediaKind.SERIES,
                title=("Example Series" if request.locale is Locale.EN else RU_SERIES),
                year=2025,
                locale=request.locale,
            ),
        )

    async def select_metadata(
        self, *, token: str, request: MetadataSelectionRequest, locale: Locale
    ) -> MediaItemDetail:
        del token, request
        return await self.get_media_item(item_id="series-1", locale=locale)

    async def import_manual(
        self, *, request: ManualImportRequest, confirmation_token: str | None = None
    ) -> ManualImportResult:
        if request.document.external_id and confirmation_token is None:
            return ManualImportResult(confirmation_token="manual-confirmation")
        return ManualImportResult(
            item=await self.get_media_item(item_id="movie-1", locale=request.document.locale)
        )

    async def edit_manual(
        self,
        *,
        item_id: str,
        document: ManualDocumentV1,
        confirmation_token: str | None = None,
    ) -> ManualImportResult:
        return await self.import_manual(
            request=ManualImportRequest(document=document),
            confirmation_token=confirmation_token or item_id,
        )

    async def import_episodes(
        self, *, item_id: str, request: EpisodeImportRequest, locale: Locale
    ) -> MediaItemDetail:
        del request
        return await self.get_media_item(item_id=item_id, locale=locale)

    async def search_releases(
        self, *, item_id: str, request: ReleaseSearchRequest
    ) -> tuple[ReleaseSearchResult, ...]:
        del item_id, request
        return (ReleaseSearchResult(token="release-pending", title="Example.Release.1080p"),)

    async def list_destinations(self) -> tuple[DownloadDestination, ...]:
        return (DownloadDestination(key="movies", label="Movies"),)

    async def submit_acquisition(self, *, request: AcquisitionSubmissionRequest) -> AcquisitionView:
        acquisition = AcquisitionView(
            id=f"{request.media_item_id}-acquisition",
            status=AcquisitionStatus.PENDING,
            release_title="Example.Release.1080p",
            destination=request.destination,
            created_at=datetime(2025, 1, 1, tzinfo=UTC),
        )
        self._acquisitions[acquisition.id] = acquisition
        return acquisition

    async def reconcile_acquisition(self, *, acquisition_id: str) -> AcquisitionView:
        acquisition = self._acquisitions[acquisition_id].model_copy(
            update={"status": AcquisitionStatus.SUBMITTED}
        )
        self._acquisitions[acquisition_id] = acquisition
        return acquisition

    async def integration_diagnostics(self) -> tuple[IntegrationDiagnostic, ...]:
        return (
            IntegrationDiagnostic(
                key="manual",
                kind="metadata_provider",
                status=ReadinessStatus.READY,
            ),
            IntegrationDiagnostic(
                key="tmdb",
                kind="metadata_provider",
                status=ReadinessStatus.UNAVAILABLE,
                error_code="metadata_provider_unavailable",
                variables=(
                    IntegrationVariableView(
                        name="MEDIA_FINDER_TMDB_API_TOKEN",
                        required=True,
                        secret=True,
                        is_set=True,
                        description_key="module.tmdb.api_token",
                    ),
                ),
            ),
        )

    async def about(self) -> AboutView:
        return AboutView(
            version="0.1.0-dev",
            attributions=(AttributionView(provider_key="manual", notice="User-provided metadata"),),
        )
