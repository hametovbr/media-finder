"""Backend implementation of the browser control application boundary."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, TypeVar

from media_finder_control import (
    AcquisitionStatus,
    ControlFailure,
    Locale,
    MediaKind,
    Page,
    PageRequest,
    ReadinessStatus,
)
from media_finder_control.manual import (
    ArtworkDocument,
    ManualDocumentV1,
    PersonDocument,
    RatingDocument,
    SeasonDocument,
)
from media_finder_control.models import (
    AboutView,
    AcquisitionSubmissionRequest,
    AcquisitionView,
    AttributionView,
    CatalogItemView,
    CollectionView,
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
from media_finder_control.models import (
    DownloadDestination as ControlDestination,
)
from media_finder_sdk import MetadataEditor, ReleaseSearchFilter
from media_finder_sdk import ReleaseSearchQuery as ModuleReleaseSearchQuery
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from .acquisition import AcquisitionRequest, AcquisitionService, DestinationUnavailable
from .domain import CatalogService, RevisionInput
from .ephemeral import EphemeralCache, EphemeralTokenExpired
from .integration_runtime import PROWLARR_INTEGRATION, RuntimeResolver
from .manual import ManualCatalogService
from .models import Acquisition, Collection, DownloadClientInstance, MediaItem, MetadataRevision
from .modules.registry import FIRST_PARTY_MODULES
from .sdk.protocols import DownloadClient
from .sdk.registration import StaticModuleRegistry
from .sdk.types import EnvironmentVariableSpec, NormalizedMetadata
from .sdk.types import MetadataSearchResult as ProviderSearchResult
from .system_clients import SYSTEM_QBITTORRENT_ID

T = TypeVar("T")


class _SimilarityConfirmationRequired(Exception):
    def __init__(self, result: ProviderSearchResult) -> None:
        self.result = result


@dataclass(frozen=True, slots=True)
class _ManualDraft:
    operation: str
    request: ManualImportRequest
    item_id: str | None = None


def _urlsafe_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _urlsafe_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}")


class CursorCodec:
    """Domain-separated signed continuation cursors."""

    def __init__(self, *, secret: bytes) -> None:
        self._secret = secret

    def encode(
        self,
        *,
        resource: str,
        filters: Mapping[str, object],
        position: tuple[str, ...],
    ) -> str:
        payload = json.dumps(
            {
                "api": "control-v1",
                "filters": filters,
                "position": position,
                "resource": resource,
                "version": 1,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        signature = hmac.new(self._secret, b"cursor-v1\0" + payload, hashlib.sha256).digest()
        return f"{_urlsafe_encode(payload)}.{_urlsafe_encode(signature)}"

    def decode(
        self,
        token: str,
        *,
        resource: str,
        filters: Mapping[str, object],
    ) -> tuple[str, ...]:
        try:
            encoded_payload, encoded_signature = token.split(".", 1)
            payload = _urlsafe_decode(encoded_payload)
            signature = _urlsafe_decode(encoded_signature)
            expected = hmac.new(self._secret, b"cursor-v1\0" + payload, hashlib.sha256).digest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError("signature")
            decoded = json.loads(payload)
            if (
                decoded.get("api") != "control-v1"
                or decoded.get("version") != 1
                or decoded.get("resource") != resource
                or decoded.get("filters") != filters
                or not isinstance(decoded.get("position"), list)
                or not all(isinstance(value, str) for value in decoded["position"])
            ):
                raise ValueError("binding")
            return tuple(decoded["position"])
        except Exception:
            raise ControlFailure(code="cursor_invalid", status=422) from None


class BackendControlGateway:
    """Async browser gateway whose worker owns each synchronous DB session."""

    def __init__(
        self,
        *,
        sessions: sessionmaker[Session],
        cursor_secret: bytes,
        runtime: RuntimeResolver | None = None,
        metadata_selections: EphemeralCache[ProviderSearchResult] | None = None,
        manual_drafts: EphemeralCache[_ManualDraft] | None = None,
        registry: StaticModuleRegistry = FIRST_PARTY_MODULES,
        build_version: str = "0.1.0",
    ) -> None:
        self._sessions = sessions
        self._cursors = CursorCodec(secret=cursor_secret)
        self._runtime = runtime
        self._metadata_selections = metadata_selections or EphemeralCache()
        self._manual_drafts = manual_drafts or EphemeralCache()
        self._registry = registry
        self._build_version = build_version

    async def _run(self, operation: Callable[[Session], T]) -> T:
        def worker() -> T:
            with self._sessions() as database:
                return operation(database)

        return await asyncio.to_thread(worker)

    async def list_collections(self, *, page: PageRequest, archived: bool) -> Page[CollectionView]:
        filters = {"archived": archived}
        position = self._decode_position(
            page.cursor,
            resource="collections",
            filters=filters,
            size=2,
        )

        def operation(database: Session) -> Page[CollectionView]:
            query = select(Collection).where(
                Collection.archived_at.is_not(None)
                if archived
                else Collection.archived_at.is_(None)
            )
            if position is not None:
                name, identifier = position
                query = query.where(
                    or_(
                        Collection.name > name,
                        and_(Collection.name == name, Collection.id > identifier),
                    )
                )
            rows = list(
                database.scalars(
                    query.order_by(Collection.name, Collection.id).limit(page.limit + 1)
                )
            )
            visible = rows[: page.limit]
            next_cursor = None
            if len(rows) > page.limit and visible:
                last = visible[-1]
                next_cursor = self._cursors.encode(
                    resource="collections",
                    filters=filters,
                    position=(last.name, last.id),
                )
            return Page(
                items=tuple(
                    CollectionView(
                        id=row.id,
                        name=row.name,
                        archived=row.archived_at is not None,
                    )
                    for row in visible
                ),
                next_cursor=next_cursor,
            )

        return await self._run(operation)

    async def create_collection(self, *, name: str) -> CollectionView:
        cleaned = name.strip()
        if not cleaned:
            raise ControlFailure(code="collection_name_required", status=422)

        def operation(database: Session) -> CollectionView:
            collection = Collection(name=cleaned)
            database.add(collection)
            try:
                database.commit()
            except IntegrityError:
                database.rollback()
                raise ControlFailure(code="collection_name_conflict", status=409) from None
            return CollectionView(id=collection.id, name=collection.name, archived=False)

        return await self._run(operation)

    async def change_collection(self, *, collection_id: str, archived: bool) -> CollectionView:
        def operation(database: Session) -> CollectionView:
            collection = database.get(Collection, collection_id)
            if collection is None:
                raise ControlFailure(code="collection_not_found", status=404)
            collection.archived_at = datetime.now(UTC) if archived else None
            database.commit()
            return CollectionView(
                id=collection.id,
                name=collection.name,
                archived=collection.archived_at is not None,
            )

        return await self._run(operation)

    async def list_media_items(
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
            page.cursor,
            resource="media-items",
            filters=filters,
            size=2,
        )

        def operation(database: Session) -> Page[CatalogItemView]:
            order_title = func.coalesce(MediaItem.normalized_title, "")
            query = select(MediaItem).where(
                MediaItem.archived_at.is_not(None) if archived else MediaItem.archived_at.is_(None)
            )
            if uncategorized:
                query = query.where(MediaItem.collection_id.is_(None))
            elif collection_id is not None:
                query = query.where(MediaItem.collection_id == collection_id)
            if position is not None:
                title, identifier = position
                query = query.where(
                    or_(
                        order_title > title,
                        and_(order_title == title, MediaItem.id > identifier),
                    )
                )
            rows = list(
                database.scalars(query.order_by(order_title, MediaItem.id).limit(page.limit + 1))
            )
            visible = rows[: page.limit]
            items = tuple(self._catalog_item(database, row, locale) for row in visible)
            next_cursor = None
            if len(rows) > page.limit and visible:
                last = visible[-1]
                next_cursor = self._cursors.encode(
                    resource="media-items",
                    filters=filters,
                    position=(last.normalized_title or "", last.id),
                )
            return Page(items=items, next_cursor=next_cursor)

        return await self._run(operation)

    async def get_media_item(self, *, item_id: str, locale: Locale) -> MediaItemDetail:
        def operation(database: Session) -> MediaItemDetail:
            item = database.get(MediaItem, item_id)
            if item is None:
                raise ControlFailure(code="media_item_not_found", status=404)
            return self._media_item_detail(database, item, locale)

        return await self._run(operation)

    async def change_media_item(
        self,
        *,
        item_id: str,
        collection_id: str | None,
        archived: bool | None,
        locale: Locale,
    ) -> MediaItemDetail:
        def operation(database: Session) -> MediaItemDetail:
            item = database.get(MediaItem, item_id)
            if item is None:
                raise ControlFailure(code="media_item_not_found", status=404)
            if collection_id is not None:
                collection = database.get(Collection, collection_id)
                if collection is None or collection.archived_at is not None:
                    raise ControlFailure(code="collection_unavailable", status=422)
            item.collection_id = collection_id
            if archived is not None:
                item.archived_at = datetime.now(UTC) if archived else None
            database.commit()
            return self._media_item_detail(database, item, locale)

        return await self._run(operation)

    async def search_metadata(
        self, *, request: MetadataSearchRequest
    ) -> tuple[MetadataSearchResult, ...]:
        runtime = self._require_runtime()

        def operation() -> list[ProviderSearchResult]:
            providers = runtime.metadata_providers()
            selected = request.provider_keys or tuple(sorted(providers))
            results: list[ProviderSearchResult] = []
            for key in selected:
                provider = providers.get(key)
                if provider is None:
                    continue
                try:
                    results.extend(provider.search(request.query, request.locale.value))
                except Exception as error:
                    raise self._failure_for(error, "metadata_provider_unavailable") from None
            return results

        provider_results = await asyncio.to_thread(operation)
        return tuple(
            MetadataSearchResult(
                token=self._metadata_selections.put(result),
                provider_key=result.provider_key,
                external_id=result.external_id,
                kind=MediaKind(result.kind.value),
                title=result.title,
                year=result.year,
                locale=Locale(result.locale),
            )
            for result in provider_results
        )

    async def select_metadata(
        self,
        *,
        token: str,
        request: MetadataSelectionRequest,
        locale: Locale,
    ) -> MetadataSelectionResult:
        try:
            result = self._metadata_selections.pop(token)
        except EphemeralTokenExpired:
            raise ControlFailure(code="selection_expired", status=410) from None
        runtime = self._require_runtime()

        def operation(database: Session) -> MetadataSelectionResult:
            exact = database.scalar(
                select(MediaItem).where(
                    MediaItem.provider_key == result.provider_key,
                    MediaItem.external_id == result.external_id,
                )
            )
            if exact is not None:
                return MetadataSelectionResult(
                    item=self._media_item_detail(database, exact, locale),
                    created=False,
                )
            catalog = CatalogService(database)
            similar = catalog.find_similar(
                result.title,
                result.year,
                excluding_provider=result.provider_key,
            )
            if similar and not request.confirm_similarity:
                raise _SimilarityConfirmationRequired(result)
            resolved = runtime.metadata_provider(result.provider_key)
            if resolved.value is None:
                raise ControlFailure(
                    code=resolved.error_code or "metadata_provider_unavailable",
                    status=503,
                )
            provider = resolved.value
            now = datetime.now(UTC)
            try:
                raw = provider.fetch(result.kind.value, result.external_id, result.locale)
                normalized = provider.normalize(
                    raw,
                    result.kind.value,
                    result.external_id,
                    result.locale,
                )
                item, _ = catalog.get_or_create_item(
                    result.provider_key,
                    result.external_id,
                    result.kind,
                )
                catalog.add_revision(
                    item,
                    RevisionInput(
                        normalized=normalized,
                        raw_payload=raw,
                        retention=provider.retention_for(now),
                        created_at=now,
                    ),
                )
                if request.collection_id is not None:
                    catalog.move_item(item, request.collection_id)
                return MetadataSelectionResult(
                    item=self._media_item_detail(database, item, locale),
                    created=True,
                )
            except ControlFailure:
                raise
            except Exception as error:
                database.rollback()
                raise self._failure_for(error, "metadata_provider_unavailable") from None

        try:
            return await self._run(operation)
        except _SimilarityConfirmationRequired as warning:
            confirmation = self._metadata_selections.put(warning.result)
            raise ControlFailure(
                code="confirmation_required",
                status=409,
                details={"confirmation_token": confirmation, "kind": "similarity"},
            ) from None

    async def import_manual(
        self,
        *,
        request: ManualImportRequest,
        confirmation_token: str | None = None,
    ) -> ManualImportResult:
        if confirmation_token is not None:
            draft = self._consume_manual_draft(confirmation_token, operation="import")
            request = draft.request
            confirm_existing = True
        else:
            confirm_existing = False
        provider = self._manual_provider()
        payload = request.document.model_dump(mode="json")

        def operation(database: Session) -> ManualImportResult:
            existing = None
            if request.document.external_id is not None:
                existing = database.scalar(
                    select(MediaItem).where(
                        MediaItem.provider_key == "manual",
                        MediaItem.external_id == request.document.external_id,
                    )
                )
            if (
                not confirm_existing
                and request.document.external_id is not None
                and existing is not None
            ):
                return ManualImportResult(
                    confirmation_token=self._manual_drafts.put(
                        _ManualDraft(operation="import", request=request)
                    )
                )
            try:
                catalog = CatalogService(database)
                item = ManualCatalogService(catalog, provider).import_json(
                    payload,
                    confirm_existing=confirm_existing,
                )
                if request.collection_id is not None:
                    catalog.move_item(item, request.collection_id)
                return ManualImportResult(
                    item=self._media_item_detail(database, item, request.document.locale),
                    created=existing is None,
                )
            except Exception as error:
                database.rollback()
                raise self._failure_for(error, "manual_import_invalid") from None

        return await self._run(operation)

    async def edit_manual(
        self,
        *,
        item_id: str,
        document: ManualDocumentV1,
        confirmation_token: str | None = None,
    ) -> ManualImportResult:
        request = ManualImportRequest(document=document)
        if confirmation_token is None:

            def prepare(database: Session) -> ManualImportResult:
                item = database.get(MediaItem, item_id)
                if (
                    item is None
                    or item.provider_key != "manual"
                    or document.external_id != item.external_id
                ):
                    raise ControlFailure(code="manual_item_not_found", status=404)
                return ManualImportResult(
                    confirmation_token=self._manual_drafts.put(
                        _ManualDraft(operation="edit", request=request, item_id=item_id)
                    )
                )

            return await self._run(prepare)
        draft = self._consume_manual_draft(confirmation_token, operation="edit")
        if draft.item_id != item_id:
            raise ControlFailure(code="selection_expired", status=410)
        provider = self._manual_provider()
        payload = draft.request.document.model_dump(mode="json")

        def apply(database: Session) -> ManualImportResult:
            item = database.get(MediaItem, item_id)
            if (
                item is None
                or item.provider_key != "manual"
                or draft.request.document.external_id != item.external_id
            ):
                raise ControlFailure(code="manual_item_not_found", status=404)
            try:
                updated = ManualCatalogService(CatalogService(database), provider).import_json(
                    payload, confirm_existing=True
                )
                return ManualImportResult(
                    item=self._media_item_detail(
                        database,
                        updated,
                        draft.request.document.locale,
                    )
                )
            except ControlFailure:
                raise
            except Exception as error:
                database.rollback()
                raise self._failure_for(error, "manual_import_invalid") from None

        return await self._run(apply)

    async def confirm_manual(self, *, token: str) -> ManualImportResult:
        try:
            draft = self._manual_drafts.pop(token)
        except EphemeralTokenExpired:
            raise ControlFailure(code="selection_expired", status=410) from None
        continuation = self._manual_drafts.put(draft)
        if draft.operation == "import":
            return await self.import_manual(
                request=draft.request,
                confirmation_token=continuation,
            )
        if draft.operation == "edit" and draft.item_id is not None:
            return await self.edit_manual(
                item_id=draft.item_id,
                document=draft.request.document,
                confirmation_token=continuation,
            )
        raise ControlFailure(code="selection_expired", status=410)

    async def import_episodes(
        self,
        *,
        item_id: str,
        request: EpisodeImportRequest,
        locale: Locale,
    ) -> MediaItemDetail:
        provider = self._manual_provider()

        def operation(database: Session) -> MediaItemDetail:
            try:
                item = ManualCatalogService(CatalogService(database), provider).import_episode_csv(
                    item_id, request.csv
                )
                return self._media_item_detail(database, item, locale)
            except Exception as error:
                database.rollback()
                raise self._failure_for(error, "manual_import_invalid") from None

        return await self._run(operation)

    async def search_releases(
        self,
        *,
        item_id: str,
        request: ReleaseSearchRequest,
    ) -> tuple[ReleaseSearchResult, ...]:
        runtime = self._require_runtime()

        def operation(database: Session) -> tuple[ReleaseSearchResult, ...]:
            item = database.get(MediaItem, item_id)
            if item is None or item.current_revision_id is None:
                raise ControlFailure(code="media_item_not_found", status=404)
            resolved = runtime.prowlarr()
            if resolved.value is None:
                raise ControlFailure(
                    code=resolved.error_code or "prowlarr_not_configured",
                    status=503,
                )
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
                results = resolved.value.search(
                    ModuleReleaseSearchQuery(query=request.query, filters=filters)
                )
            except Exception as error:
                raise self._failure_for(error, "prowlarr_search_failed") from None
            return tuple(
                ReleaseSearchResult(
                    token=result.token,
                    title=result.title,
                    indexer=result.indexer,
                )
                for result in results
            )

        return await self._run(operation)

    async def list_destinations(self) -> tuple[ControlDestination, ...]:
        def operation(database: Session) -> tuple[ControlDestination, ...]:
            instance = database.get(DownloadClientInstance, SYSTEM_QBITTORRENT_ID)
            if instance is None:
                raise ControlFailure(code="download_client_not_found", status=404)
            try:
                destinations = self._load_client(instance).list_destinations()
                return tuple(
                    ControlDestination(key=value.key, label=value.label) for value in destinations
                )
            except ControlFailure:
                raise
            except Exception as error:
                raise self._failure_for(error, "download_client_destinations_unavailable") from None

        return await self._run(operation)

    async def submit_acquisition(self, *, request: AcquisitionSubmissionRequest) -> AcquisitionView:
        runtime = self._require_runtime()

        def operation(database: Session) -> AcquisitionView:
            item = database.get(MediaItem, request.media_item_id)
            if item is None or item.current_revision_id is None:
                raise ControlFailure(code="media_item_not_found", status=404)
            service = AcquisitionService(
                database,
                runtime.prowlarr().value,
                self._load_client,
            )
            try:
                acquisition = service.submit(
                    AcquisitionRequest(
                        media_item_id=item.id,
                        metadata_revision_id=item.current_revision_id,
                        client_instance_id=SYSTEM_QBITTORRENT_ID,
                        destination=request.destination,
                        release_token=request.release_token,
                        idempotency_key=request.idempotency_key,
                    )
                )
                return self._acquisition_view(acquisition)
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
            except ControlFailure:
                raise
            except Exception as error:
                raise self._failure_for(error, "acquisition_unavailable") from None

        return await self._run(operation)

    async def reconcile_acquisition(self, *, acquisition_id: str) -> AcquisitionView:
        def operation(database: Session) -> AcquisitionView:
            try:
                acquisition = AcquisitionService(
                    database,
                    None,
                    self._load_client,
                ).reconcile(acquisition_id)
                return self._acquisition_view(acquisition)
            except Exception as error:
                raise self._failure_for(error, "acquisition_unavailable") from None

        return await self._run(operation)

    async def metadata_providers(self) -> tuple[MetadataProviderView, ...]:
        runtime = self._require_runtime()

        def operation() -> tuple[MetadataProviderView, ...]:
            values: list[MetadataProviderView] = []
            for key in sorted(self._registry.metadata_providers):
                prototype = runtime.supported_providers.get(key)
                result = runtime.metadata_provider(key)
                provider = result.value or prototype
                if provider is None:
                    continue
                values.append(
                    MetadataProviderView(
                        key=key,
                        name_key=provider.manifest.name_key,
                        capabilities=provider.manifest.capabilities,
                        ready=result.value is not None,
                        attribution_key=key,
                    )
                )
            return tuple(values)

        return await asyncio.to_thread(operation)

    async def integration_diagnostics(self) -> tuple[IntegrationDiagnostic, ...]:
        runtime = self._require_runtime()

        def operation(database: Session) -> tuple[IntegrationDiagnostic, ...]:
            diagnostics: list[IntegrationDiagnostic] = []
            for key, registration in sorted(self._registry.metadata_providers.items()):
                provider_result = runtime.metadata_provider(key)
                diagnostics.append(
                    self._diagnostic(
                        key=key,
                        kind="metadata_provider",
                        declarations=registration.environment,
                        result_value=provider_result.value,
                        error_code=provider_result.error_code,
                    )
                )
            prowlarr_result = runtime.prowlarr()
            diagnostics.append(
                self._diagnostic(
                    key="prowlarr",
                    kind="release_search",
                    declarations=PROWLARR_INTEGRATION.environment,
                    result_value=prowlarr_result.value,
                    error_code=prowlarr_result.error_code,
                )
            )
            instance = database.get(DownloadClientInstance, SYSTEM_QBITTORRENT_ID)
            client_value: object | None
            client_error: str | None
            if instance is None:
                client_value = None
                client_error = "download_client_not_found"
            else:
                client_result = runtime.download_client(instance)
                client_value = client_result.value
                client_error = client_result.error_code
            client_registration = self._registry.download_clients["qbittorrent"]
            diagnostics.append(
                self._diagnostic(
                    key="qbittorrent",
                    kind="download_client",
                    declarations=client_registration.environment,
                    result_value=client_value,
                    error_code=client_error,
                )
            )
            return tuple(diagnostics)

        return await self._run(operation)

    async def about(self) -> AboutView:
        runtime = self._require_runtime()

        def operation() -> AboutView:
            attributions = [factory() for factory in self._registry.static_attributions]
            attributions.extend(runtime.configured_provider_attributions())
            return AboutView(
                version=self._build_version,
                attributions=tuple(
                    AttributionView(
                        provider_key=value.provider_key,
                        notice=value.notice,
                        url=value.url,
                    )
                    for value in attributions
                ),
            )

        return await asyncio.to_thread(operation)

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

    def _require_runtime(self) -> RuntimeResolver:
        if self._runtime is None:
            raise ControlFailure(code="integration_runtime_unavailable", status=503)
        return self._runtime

    def _manual_provider(self) -> MetadataEditor:
        resolved = self._require_runtime().metadata_provider("manual")
        if resolved.value is None:
            raise ControlFailure(
                code=resolved.error_code or "metadata_provider_unavailable",
                status=503,
            )
        if not isinstance(resolved.value, MetadataEditor):
            raise ControlFailure(code="metadata_editor_unavailable", status=503)
        return resolved.value

    def _load_client(self, instance: DownloadClientInstance) -> DownloadClient:
        if instance.archived_at is not None:
            raise ControlFailure(code="download_client_archived", status=422)
        resolved = self._require_runtime().download_client(instance)
        if resolved.value is None:
            raise ControlFailure(
                code=resolved.error_code or "download_client_unavailable",
                status=503,
            )
        return resolved.value

    def _diagnostic(
        self,
        *,
        key: str,
        kind: Literal["metadata_provider", "download_client", "release_search"],
        declarations: tuple[EnvironmentVariableSpec, ...],
        result_value: object | None,
        error_code: str | None,
    ) -> IntegrationDiagnostic:
        variables = tuple(
            IntegrationVariableView(
                name=declaration.name,
                required=declaration.required,
                secret=declaration.secret,
                is_set=self._require_runtime().environment_is_set(declaration.name),
                description_key=declaration.description_key,
            )
            for declaration in declarations
        )
        missing = any(value.required and not value.is_set for value in variables)
        status = (
            ReadinessStatus.MISSING
            if missing
            else (
                ReadinessStatus.READY if result_value is not None else ReadinessStatus.UNAVAILABLE
            )
        )
        return IntegrationDiagnostic(
            key=key,
            kind=kind,
            status=status,
            error_code=None if status is ReadinessStatus.READY else error_code,
            variables=variables,
        )

    def _consume_manual_draft(self, token: str, *, operation: str) -> _ManualDraft:
        try:
            draft = self._manual_drafts.pop(token)
        except EphemeralTokenExpired:
            raise ControlFailure(code="selection_expired", status=410) from None
        if draft.operation != operation:
            raise ControlFailure(code="selection_expired", status=410)
        return draft

    @staticmethod
    def _failure_for(error: Exception, fallback: str) -> ControlFailure:
        code = getattr(error, "code", fallback)
        if code == fallback and error.args and isinstance(error.args[0], str):
            candidate = error.args[0]
            if (
                candidate
                and len(candidate) <= 200
                and all(
                    character in "abcdefghijklmnopqrstuvwxyz0123456789_-" for character in candidate
                )
            ):
                code = candidate
        if not isinstance(code, str) or not code:
            code = fallback
        if code.endswith("_not_found"):
            status = 404
        elif "unavailable" in code or "not_configured" in code:
            status = 503
        else:
            status = 422
        return ControlFailure(code=code, status=status)

    @staticmethod
    def _acquisition_view(acquisition: Acquisition) -> AcquisitionView:
        return AcquisitionView(
            id=str(acquisition.id),
            media_item_id=acquisition.media_item_id,
            status=AcquisitionStatus(acquisition.status),
            release_title=acquisition.release_title or "",
            destination=acquisition.destination,
            created_at=acquisition.created_at,
            error_code=acquisition.failure_code,
        )

    @staticmethod
    def _media_item_detail(database: Session, item: MediaItem, locale: Locale) -> MediaItemDetail:
        revision = database.get(MetadataRevision, item.current_revision_id)
        if revision is None or revision.effective_payload is None:
            raise ControlFailure(code="metadata_unavailable", status=410)
        try:
            metadata = NormalizedMetadata.model_validate(revision.effective_payload)
        except Exception:
            raise ControlFailure(code="metadata_unavailable", status=410) from None
        acquisitions = tuple(
            AcquisitionView(
                id=str(acquisition.id),
                media_item_id=acquisition.media_item_id,
                status=AcquisitionStatus(acquisition.status),
                release_title=acquisition.release_title or "",
                destination=acquisition.destination,
                created_at=acquisition.created_at,
                error_code=acquisition.failure_code,
            )
            for acquisition in database.scalars(
                select(Acquisition)
                .where(Acquisition.media_item_id == item.id)
                .order_by(Acquisition.created_at.desc(), Acquisition.id.desc())
            )
        )
        projected = MetadataView(
            kind=MediaKind(metadata.kind.value),
            titles=dict(metadata.titles),
            original_title=metadata.original_title,
            year=metadata.year,
            plot=metadata.plot,
            release_date=metadata.release_date,
            runtime_minutes=metadata.runtime_minutes,
            provider_ids=dict(metadata.provider_ids),
            ratings=tuple(
                RatingDocument.model_validate(rating.model_dump()) for rating in metadata.ratings
            ),
            genres=metadata.genres,
            tags=metadata.tags,
            countries=metadata.countries,
            studios=metadata.studios,
            people=tuple(
                PersonDocument.model_validate(person.model_dump()) for person in metadata.people
            ),
            artwork=tuple(
                ArtworkDocument.model_validate(artwork.model_dump(mode="json"))
                for artwork in metadata.artwork
            ),
            seasons=tuple(
                SeasonDocument.model_validate(season.model_dump(mode="json"))
                for season in metadata.seasons
            ),
        )
        return MediaItemDetail(
            id=item.id,
            provider_key=item.provider_key,
            external_id=item.external_id,
            kind=MediaKind(item.kind),
            collection_id=item.collection_id,
            archived=item.archived_at is not None,
            metadata=projected,
            acquisitions=acquisitions,
        )

    @staticmethod
    def _catalog_item(database: Session, item: MediaItem, locale: Locale) -> CatalogItemView:
        revision = database.get(MetadataRevision, item.current_revision_id)
        payload = revision.effective_payload if revision and revision.effective_payload else {}
        raw_titles = payload.get("titles")
        titles: dict[str, object] = raw_titles if isinstance(raw_titles, dict) else {}
        title = titles.get(locale.value) or next(iter(titles.values()), item.external_id)
        poster_url = None
        for artwork in payload.get("artwork", ()):
            if isinstance(artwork, dict) and str(artwork.get("kind", "")).casefold() == "poster":
                poster_url = artwork.get("url")
                break
        latest = database.scalar(
            select(Acquisition)
            .where(Acquisition.media_item_id == item.id)
            .order_by(Acquisition.created_at.desc(), Acquisition.id.desc())
            .limit(1)
        )
        return CatalogItemView(
            id=item.id,
            title=str(title),
            year=item.year,
            kind=MediaKind(item.kind),
            provider_key=item.provider_key,
            latest_acquisition_status=(
                AcquisitionStatus(latest.status) if latest is not None else None
            ),
            poster_url=poster_url,
            archived=item.archived_at is not None,
        )
