"""Portable browser-control orchestration and projection for the catalog."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime

from media_finder_control import (
    AcquisitionStatus,
    ControlFailure,
    Locale,
    MediaKind,
    Page,
    PageRequest,
)
from media_finder_control.manual import (
    ArtworkDocument,
    PersonDocument,
    RatingDocument,
    SeasonDocument,
)
from media_finder_control.models import (
    AcquisitionView,
    CatalogItemView,
    CollectionView,
    MediaItemDetail,
    MetadataView,
)

from media_finder_core.acquisition.models import AcquisitionSnapshot
from media_finder_core.acquisition.ports import AcquisitionQueryPort
from media_finder_core.acquisition.queries import AcquisitionQueries
from media_finder_core.catalog.commands import CatalogCommands
from media_finder_core.catalog.models import MediaItemSnapshot
from media_finder_core.catalog.ports import CatalogQueryPort, CatalogUnitOfWork
from media_finder_core.catalog.queries import CatalogQueries
from media_finder_core.control.security import ControlPortError, CursorCodec, invoke

__all__ = ["CatalogControlService", "CatalogViewProjector"]

_CATALOG_CODES = {
    "catalog_query_limit_invalid",
    "collection_name_required",
    "collection_not_found",
    "collection_unavailable",
    "media_item_not_found",
    "media_item_unavailable",
}


class CatalogViewProjector:
    """Project immutable core snapshots into stable browser DTOs."""

    def __init__(
        self,
        *,
        catalog: CatalogQueryPort,
        acquisitions: AcquisitionQueryPort,
    ) -> None:
        self._catalog = catalog
        self._acquisitions = AcquisitionQueries(query_port=acquisitions)

    def item_detail(self, item_id: str, locale: Locale) -> MediaItemDetail:
        item = self._catalog.get_item(item_id)
        if item is None:
            raise ControlFailure(code="media_item_not_found", status=404)
        revision = (
            self._catalog.get_revision(item.current_revision_id)
            if item.current_revision_id is not None
            else None
        )
        if revision is None or revision.effective is None:
            raise ControlFailure(code="metadata_unavailable", status=410)
        return MediaItemDetail(
            id=item.id,
            provider_key=item.identity.provider_id,
            external_id=item.identity.external_id,
            kind=MediaKind(item.identity.media_kind.value),
            collection_id=item.collection_id,
            archived=item.archived_at is not None,
            metadata=_metadata_view(revision.effective),
            acquisitions=tuple(
                _acquisition_view(value)
                for value in self._acquisitions.for_media_item(item.id, limit=100)
            ),
        )

    def catalog_item(self, item: MediaItemSnapshot, locale: Locale) -> CatalogItemView:
        revision = (
            self._catalog.get_revision(item.current_revision_id)
            if item.current_revision_id is not None
            else None
        )
        metadata = revision.effective if revision is not None else None
        titles = dict(metadata.titles) if metadata is not None else {}
        title = titles.get(locale.value) or next(iter(titles.values()), item.identity.external_id)
        poster_url = (
            next(
                (
                    artwork.url
                    for artwork in metadata.artwork
                    if artwork.kind.casefold() == "poster"
                ),
                None,
            )
            if metadata is not None
            else None
        )
        latest = self._acquisitions.for_media_item(item.id, limit=1)
        return CatalogItemView(
            id=item.id,
            title=title,
            year=item.year,
            kind=MediaKind(item.identity.media_kind.value),
            provider_key=item.identity.provider_id,
            latest_acquisition_status=(
                AcquisitionStatus(latest[0].status.value) if latest else None
            ),
            poster_url=poster_url,
            archived=item.archived_at is not None,
        )


class CatalogControlService:
    """Own catalog commands, pagination cursors, and DTO projection."""

    def __init__(
        self,
        *,
        query_port: CatalogQueryPort,
        unit_of_work: CatalogUnitOfWork,
        projector: CatalogViewProjector,
        cursor_secret: bytes,
        clock: Callable[[], datetime],
    ) -> None:
        self._queries = CatalogQueries(query_port=query_port)
        self._uow = unit_of_work
        self._projector = projector
        self._cursors = CursorCodec(secret=cursor_secret)
        self._clock = clock

    async def list_collections(self, *, page: PageRequest, archived: bool) -> Page[CollectionView]:
        return await invoke(
            lambda: self._list_collections(page=page, archived=archived),
            fallback="catalog_unavailable",
        )

    def _list_collections(self, *, page: PageRequest, archived: bool) -> Page[CollectionView]:
        filters = {"archived": archived}
        position = self._decode_position(
            page.cursor, resource="collections", filters=filters, size=2
        )
        try:
            result = self._queries.list_collections(
                archived=archived,
                limit=page.limit,
                after=(position[0], position[1]) if position is not None else None,
            )
        except ValueError as error:
            raise _catalog_error(error, "catalog_unavailable") from None
        next_cursor = (
            self._cursors.encode(
                resource="collections", filters=filters, position=result.next_after
            )
            if result.next_after is not None
            else None
        )
        return Page(
            items=tuple(
                CollectionView(
                    id=value.id,
                    name=value.name,
                    archived=value.archived_at is not None,
                )
                for value in result.items
            ),
            next_cursor=next_cursor,
        )

    async def create_collection(self, *, name: str) -> CollectionView:
        return await invoke(
            lambda: self._create_collection(name), fallback="collection_unavailable"
        )

    def _create_collection(self, name: str) -> CollectionView:
        cleaned = name.strip()
        if not cleaned:
            raise ControlFailure(code="collection_name_required", status=422)
        try:
            with self._uow.write() as repository:
                value = CatalogCommands(repository=repository, clock=self._clock).create_collection(
                    cleaned
                )
        except ValueError as error:
            raise _catalog_error(error, "collection_unavailable") from None
        return CollectionView(id=value.id, name=value.name, archived=False)

    async def change_collection(self, *, collection_id: str, archived: bool) -> CollectionView:
        return await invoke(
            lambda: self._change_collection(collection_id, archived),
            fallback="collection_unavailable",
        )

    def _change_collection(self, collection_id: str, archived: bool) -> CollectionView:
        try:
            with self._uow.write() as repository:
                commands = CatalogCommands(repository=repository, clock=self._clock)
                value = (
                    commands.archive_collection(collection_id)
                    if archived
                    else commands.restore_collection(collection_id)
                )
        except ValueError as error:
            raise _catalog_error(error, "collection_unavailable") from None
        return CollectionView(id=value.id, name=value.name, archived=value.archived_at is not None)

    async def list_media_items(
        self,
        *,
        locale: Locale,
        page: PageRequest,
        collection_id: str | None,
        uncategorized: bool,
        archived: bool,
    ) -> Page[CatalogItemView]:
        return await invoke(
            lambda: self._list_media_items(
                locale=locale,
                page=page,
                collection_id=collection_id,
                uncategorized=uncategorized,
                archived=archived,
            ),
            fallback="catalog_unavailable",
        )

    def _list_media_items(
        self,
        *,
        locale: Locale,
        page: PageRequest,
        collection_id: str | None,
        uncategorized: bool,
        archived: bool,
    ) -> Page[CatalogItemView]:
        filters = {
            "archived": archived,
            "collection_id": collection_id,
            "locale": locale.value,
            "uncategorized": uncategorized,
        }
        position = self._decode_position(
            page.cursor, resource="media-items", filters=filters, size=2
        )
        try:
            result = self._queries.list_items(
                archived=archived,
                collection_id=collection_id,
                uncategorized=uncategorized,
                limit=page.limit,
                after=(position[0], position[1]) if position is not None else None,
            )
        except ValueError as error:
            raise _catalog_error(error, "catalog_unavailable") from None
        next_cursor = (
            self._cursors.encode(
                resource="media-items", filters=filters, position=result.next_after
            )
            if result.next_after is not None
            else None
        )
        return Page(
            items=tuple(self._projector.catalog_item(value, locale) for value in result.items),
            next_cursor=next_cursor,
        )

    async def get_media_item(self, *, item_id: str, locale: Locale) -> MediaItemDetail:
        return await invoke(
            lambda: self._projector.item_detail(item_id, locale),
            fallback="media_item_unavailable",
        )

    async def change_media_item(
        self,
        *,
        item_id: str,
        collection_id: str | None,
        archived: bool | None,
        locale: Locale,
    ) -> MediaItemDetail:
        return await invoke(
            lambda: self._change_media_item(
                item_id=item_id,
                collection_id=collection_id,
                archived=archived,
                locale=locale,
            ),
            fallback="media_item_unavailable",
        )

    def _change_media_item(
        self,
        *,
        item_id: str,
        collection_id: str | None,
        archived: bool | None,
        locale: Locale,
    ) -> MediaItemDetail:
        try:
            with self._uow.write() as repository:
                commands = CatalogCommands(repository=repository, clock=self._clock)
                commands.move_item(item_id, collection_id)
                if archived is True:
                    commands.archive_item(item_id)
                elif archived is False:
                    commands.restore_item(item_id)
        except ValueError as error:
            raise _catalog_error(error, "media_item_unavailable") from None
        return self._projector.item_detail(item_id, locale)

    def _decode_position(
        self,
        cursor: str | None,
        *,
        resource: str,
        filters: Mapping[str, object],
        size: int,
    ) -> tuple[str, ...] | None:
        if cursor is None:
            return None
        position = self._cursors.decode(cursor, resource=resource, filters=filters)
        if len(position) != size:
            raise ControlFailure(code="cursor_invalid", status=422)
        return position


def _catalog_error(error: ValueError, fallback: str) -> ControlPortError:
    code = str(error)
    return ControlPortError(code if code in _CATALOG_CODES else fallback)


def _metadata_view(metadata: object) -> MetadataView:
    from media_finder_sdk import NormalizedMetadata

    value = NormalizedMetadata.model_validate(metadata)
    return MetadataView(
        kind=MediaKind(value.kind.value),
        titles=dict(value.titles),
        original_title=value.original_title,
        year=value.year,
        plot=value.plot,
        release_date=value.release_date,
        runtime_minutes=value.runtime_minutes,
        provider_ids=dict(value.provider_ids),
        ratings=tuple(RatingDocument.model_validate(item.model_dump()) for item in value.ratings),
        genres=value.genres,
        tags=value.tags,
        countries=value.countries,
        studios=value.studios,
        people=tuple(PersonDocument.model_validate(item.model_dump()) for item in value.people),
        artwork=tuple(
            ArtworkDocument.model_validate(item.model_dump(mode="json")) for item in value.artwork
        ),
        seasons=tuple(
            SeasonDocument.model_validate(item.model_dump(mode="json")) for item in value.seasons
        ),
    )


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
