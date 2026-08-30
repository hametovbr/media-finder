"""Safe browser-facing control data transfer objects."""

from datetime import date, datetime
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, HttpUrl, model_validator

from .common import (
    AcquisitionStatus,
    ControlModel,
    Locale,
    MediaKind,
    ReadinessStatus,
)
from .manual import (
    ArtworkDocument,
    ManualDocumentV1,
    PersonDocument,
    RatingDocument,
    SeasonDocument,
)


class BrowserSession(ControlModel):
    ui_locale: Locale
    metadata_locale: Locale
    csrf_token: str = Field(min_length=1)
    supported_locales: tuple[Locale, ...] = (Locale.EN, Locale.RU)
    metadata_locale_explicit: bool = Field(default=False, exclude=True)
    is_new: bool = Field(default=False, exclude=True)


class SessionView(ControlModel):
    ui_locale: Locale
    metadata_locale: Locale
    csrf_token: str
    supported_locales: tuple[Locale, ...]

    @classmethod
    def from_session(cls, session: BrowserSession) -> "SessionView":
        return cls(
            ui_locale=session.ui_locale,
            metadata_locale=session.metadata_locale,
            csrf_token=session.csrf_token,
            supported_locales=session.supported_locales,
        )


class SessionUpdate(ControlModel):
    ui_locale: Locale | None = None
    metadata_locale: Locale | None = None


class CollectionView(ControlModel):
    id: str
    name: str
    archived: bool = False


class CollectionCreateRequest(ControlModel):
    name: str = Field(min_length=1, max_length=200)


class CollectionChangeRequest(ControlModel):
    archived: bool


class MediaItemOperation(StrEnum):
    MOVE = "move"
    ARCHIVE = "archive"
    RESTORE = "restore"


class MediaItemChangeRequest(ControlModel):
    operation: MediaItemOperation
    collection_id: str | None = None
    locale: Locale = Locale.EN

    @model_validator(mode="after")
    def require_explicit_move_target(self) -> Self:
        if (
            self.operation is MediaItemOperation.MOVE
            and "collection_id" not in self.model_fields_set
        ):
            raise ValueError("collection_id is required for a move operation")
        return self


class CatalogItemView(ControlModel):
    id: str
    title: str
    year: int | None = None
    kind: MediaKind
    provider_key: str
    latest_acquisition_status: AcquisitionStatus | None = None
    poster_url: HttpUrl | None = None
    archived: bool = False


class MetadataView(ControlModel):
    kind: MediaKind
    titles: dict[str, str]
    original_title: str | None = None
    year: int | None = None
    plot: str | None = None
    release_date: date | None = None
    runtime_minutes: int | None = None
    provider_ids: dict[str, str] = Field(default_factory=dict)
    ratings: tuple[RatingDocument, ...] = ()
    genres: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    countries: tuple[str, ...] = ()
    studios: tuple[str, ...] = ()
    people: tuple[PersonDocument, ...] = ()
    artwork: tuple[ArtworkDocument, ...] = ()
    seasons: tuple[SeasonDocument, ...] = ()


class AcquisitionView(ControlModel):
    id: str
    media_item_id: str
    status: AcquisitionStatus
    release_title: str
    destination: str
    created_at: datetime
    error_code: str | None = None


class MediaItemDetail(ControlModel):
    id: str
    provider_key: str
    external_id: str
    kind: MediaKind
    collection_id: str | None = None
    archived: bool = False
    metadata: MetadataView
    acquisitions: tuple[AcquisitionView, ...] = ()


class MetadataProviderView(ControlModel):
    key: str
    name_key: str
    capabilities: frozenset[str] = frozenset()
    ready: bool
    attribution_key: str | None = None


class MetadataSearchRequest(ControlModel):
    query: str = Field(min_length=1, max_length=512)
    locale: Locale
    provider_keys: tuple[str, ...] = ()


class MetadataSearchResult(ControlModel):
    token: str
    provider_key: str
    external_id: str
    kind: MediaKind
    title: str
    year: int | None = None
    locale: Locale
    description: str | None = None
    poster_url: HttpUrl | None = None


class MetadataSelectionRequest(ControlModel):
    collection_id: str | None = None
    confirm_similarity: bool = False


class MetadataSelectionResult(ControlModel):
    item: MediaItemDetail
    created: bool


class ManualImportRequest(ControlModel):
    document: ManualDocumentV1
    collection_id: str | None = None


class ManualImportResult(ControlModel):
    item: MediaItemDetail | None = None
    confirmation_token: str | None = None
    created: bool = False


class EpisodeImportRequest(ControlModel):
    csv: str = Field(max_length=1_048_576)


class ReleaseSearchRequest(ControlModel):
    query: str = Field(min_length=1, max_length=512)
    indexer_ids: tuple[int, ...] = ()


class ReleaseSearchResult(ControlModel):
    token: str
    title: str
    indexer: str | None = None
    size: int | None = None
    seeders: int | None = None


class DownloadDestination(ControlModel):
    key: str
    label: str


class AcquisitionSubmissionRequest(ControlModel):
    media_item_id: str
    release_token: str
    destination: str
    idempotency_key: str = Field(min_length=1, max_length=255)


class IntegrationVariableView(ControlModel):
    name: str
    required: bool
    secret: bool
    is_set: bool
    description_key: str


class IntegrationDiagnostic(ControlModel):
    key: str
    kind: Literal["metadata_provider", "download_client", "release_search"]
    status: ReadinessStatus
    error_code: str | None = None
    variables: tuple[IntegrationVariableView, ...] = ()


class AttributionView(ControlModel):
    provider_key: str
    notice: str
    url: HttpUrl | None = None


class AboutView(ControlModel):
    version: str
    attributions: tuple[AttributionView, ...] = ()
