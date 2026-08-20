"""Deterministic in-memory control gateway for control API tests."""

from datetime import UTC, datetime

from media_finder_control import (
    AcquisitionStatus,
    ControlFailure,
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
    BrowserSession,
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
    MetadataSelectionResult,
    MetadataView,
    ReleaseSearchRequest,
    ReleaseSearchResult,
)

RU_EXAMPLE = "\u041f\u0440\u0438\u043c\u0435\u0440"
RU_MOVIE = f"{RU_EXAMPLE} \u0444\u0438\u043b\u044c\u043c\u0430"
RU_SERIES = f"{RU_EXAMPLE} \u0441\u0435\u0440\u0438\u0430\u043b\u0430"


class FakeBrowserSecurity:
    """Deterministic browser security port for isolated UI development."""

    def __init__(self) -> None:
        self._session: BrowserSession | None = None

    async def load_session(
        self, *, cookie: str | None, accept_language: str | None
    ) -> BrowserSession:
        if cookie is not None and self._session is not None:
            return self._session.model_copy(update={"is_new": False})
        locale = Locale.RU if (accept_language or "").casefold().startswith("ru") else Locale.EN
        return BrowserSession(
            ui_locale=locale,
            metadata_locale=locale,
            csrf_token="fake-csrf-token",
            is_new=cookie is None,
        )

    async def serialize_session(self, *, session: BrowserSession) -> str:
        self._session = session.model_copy(update={"is_new": False})
        return "fake-session"

    async def validate_csrf(self, *, session: BrowserSession, token: str | None) -> bool:
        return token == session.csrf_token


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
        query = request.query.casefold()
        if "duplicate" in query:
            token = "metadata-duplicate"
        elif "similar" in query:
            token = "metadata-similar"
        else:
            token = "metadata-1"
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
    ) -> MetadataSelectionResult:
        del request
        if token == "metadata-expired":
            raise ControlFailure(code="selection_expired", status=410)
        if token == "metadata-similar":
            raise ControlFailure(
                code="confirmation_required",
                status=409,
                details={"confirmation_token": "metadata-confirmed", "kind": "similarity"},
            )
        return MetadataSelectionResult(
            item=await self.get_media_item(item_id="series-1", locale=locale),
            created=token != "metadata-duplicate",
        )

    async def import_manual(
        self, *, request: ManualImportRequest, confirmation_token: str | None = None
    ) -> ManualImportResult:
        if request.document.external_id and confirmation_token is None:
            return ManualImportResult(confirmation_token="manual-confirmation")
        return ManualImportResult(
            item=await self.get_media_item(item_id="movie-1", locale=request.document.locale),
            created=request.document.external_id is None,
        )

    async def edit_manual(
        self,
        *,
        item_id: str,
        document: ManualDocumentV1,
        confirmation_token: str | None = None,
    ) -> ManualImportResult:
        if confirmation_token is None:
            return ManualImportResult(confirmation_token="manual-edit-confirmation")
        return await self.import_manual(
            request=ManualImportRequest(document=document),
            confirmation_token=confirmation_token or item_id,
        )

    async def confirm_manual(self, *, token: str) -> ManualImportResult:
        del token
        return ManualImportResult(
            item=await self.get_media_item(item_id="movie-1", locale=Locale.EN),
            created=False,
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
            media_item_id=request.media_item_id,
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
