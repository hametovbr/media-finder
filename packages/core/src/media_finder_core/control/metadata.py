"""Portable browser-control orchestration for metadata and manual editing."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from media_finder_control import ControlFailure, Locale, MediaKind
from media_finder_control.manual import ManualDocumentV1
from media_finder_control.models import (
    EpisodeImportRequest,
    ManualImportRequest,
    ManualImportResult,
    MediaItemDetail,
    MetadataProviderView,
    MetadataSearchRequest,
    MetadataSearchResult,
    MetadataSelectionRequest,
    MetadataSelectionResult,
)
from media_finder_sdk import (
    EpisodeTableDocument,
    MetadataEditor,
    MetadataIdentity,
    MetadataImportDocument,
    MetadataProvider,
    MetadataRetentionPolicy,
    MetadataSearchQuery,
)
from media_finder_sdk import (
    MetadataSearchResult as CoreMetadataSearchResult,
)

from media_finder_core.catalog.manual import ManualCatalogService
from media_finder_core.catalog.metadata import MetadataCatalogService
from media_finder_core.catalog.ports import CatalogQueryPort, CatalogUnitOfWork
from media_finder_core.control.catalog import CatalogViewProjector
from media_finder_core.control.security import ControlPortError, invoke
from media_finder_core.platform.cache import EphemeralCache, EphemeralTokenExpired

__all__ = [
    "ManualDraft",
    "MetadataControlModules",
    "MetadataControlService",
    "MetadataModuleDescriptor",
]

_METADATA_CODES = {
    "catalog_current_revision_changed",
    "duplicate_confirmation_required",
    "manual_import_invalid",
    "manual_item_not_found",
    "metadata_editor_unavailable",
    "metadata_import_invalid",
    "metadata_provider_not_found",
    "metadata_provider_unavailable",
    "provider_identity_mismatch",
    "similarity_confirmation_required",
}


@dataclass(frozen=True, slots=True)
class ManualDraft:
    operation: str
    request: ManualImportRequest
    item_id: str | None = None
    expected_current_revision_id: str | None = None


@dataclass(frozen=True, slots=True)
class MetadataModuleDescriptor:
    module_id: str
    name_key: str
    capabilities: frozenset[str]
    ready: bool


class MetadataControlModules(Protocol):
    """Narrow metadata-module access needed by control orchestration."""

    def provider_ids(self) -> tuple[str, ...]: ...

    def editor_ids(self) -> tuple[str, ...]: ...

    def descriptors(self) -> tuple[MetadataModuleDescriptor, ...]: ...

    def metadata_provider(self, module_id: str) -> MetadataProvider: ...

    def metadata_editor(self, module_id: str) -> MetadataEditor: ...

    def retention_policy(self, module_id: str) -> MetadataRetentionPolicy: ...


class MetadataControlService:
    """Own provider selection, opaque tokens, confirmations, and metadata edits."""

    def __init__(
        self,
        *,
        query_port: CatalogQueryPort,
        unit_of_work: CatalogUnitOfWork,
        modules: MetadataControlModules,
        projector: CatalogViewProjector,
        clock: Callable[[], datetime],
        metadata_selections: EphemeralCache[CoreMetadataSearchResult],
        manual_drafts: EphemeralCache[ManualDraft],
    ) -> None:
        self._queries = query_port
        self._uow = unit_of_work
        self._modules = modules
        self._projector = projector
        self._clock = clock
        self._metadata_selections = metadata_selections
        self._manual_drafts = manual_drafts

    async def metadata_providers(self) -> tuple[MetadataProviderView, ...]:
        return await invoke(self._metadata_providers, fallback="metadata_provider_unavailable")

    def _metadata_providers(self) -> tuple[MetadataProviderView, ...]:
        return tuple(
            MetadataProviderView(
                key=value.module_id,
                name_key=value.name_key,
                capabilities=value.capabilities,
                ready=value.ready,
                attribution_key=value.module_id,
            )
            for value in self._modules.descriptors()
        )

    async def search_metadata(
        self, *, request: MetadataSearchRequest
    ) -> tuple[MetadataSearchResult, ...]:
        return await invoke(
            lambda: self._search_metadata(request),
            fallback="metadata_provider_unavailable",
        )

    def _search_metadata(self, request: MetadataSearchRequest) -> tuple[MetadataSearchResult, ...]:
        selected = request.provider_keys or self._modules.provider_ids()
        try:
            results = MetadataCatalogService(
                query_port=self._queries,
                unit_of_work=self._uow,
                clock=self._clock,
            ).search(
                query=MetadataSearchQuery(
                    query=request.query,
                    locale=request.locale.value,
                ),
                providers={key: self._modules.metadata_provider(key) for key in selected},
                selected_provider_ids=selected,
            )
        except ControlPortError:
            raise
        except Exception as error:
            raise _metadata_error(error, "metadata_provider_unavailable") from None
        return tuple(
            MetadataSearchResult(
                token=self._metadata_selections.put(value),
                provider_key=value.provider_id,
                external_id=value.external_id,
                kind=MediaKind(value.media_kind.value),
                title=value.title,
                year=value.year,
                locale=Locale(value.locale),
                description=value.description,
                poster_url=value.poster_url,
            )
            for value in results
        )

    async def select_metadata(
        self, *, token: str, request: MetadataSelectionRequest, locale: Locale
    ) -> MetadataSelectionResult:
        return await invoke(
            lambda: self._select_metadata(token=token, request=request, locale=locale),
            fallback="metadata_provider_unavailable",
        )

    def _select_metadata(
        self, *, token: str, request: MetadataSelectionRequest, locale: Locale
    ) -> MetadataSelectionResult:
        try:
            result = self._metadata_selections.pop(token)
        except EphemeralTokenExpired:
            raise ControlFailure(code="selection_expired", status=410) from None
        identity = MetadataIdentity(
            provider_id=result.provider_id,
            external_id=result.external_id,
            media_kind=result.media_kind,
            locale=result.locale,
        )
        try:
            outcome = MetadataCatalogService(
                query_port=self._queries,
                unit_of_work=self._uow,
                clock=self._clock,
            ).select(
                identity=identity,
                provider=lambda: self._modules.metadata_provider(result.provider_id),
                retention_policy=lambda: self._modules.retention_policy(result.provider_id),
                confirm_similarity=request.confirm_similarity,
                collection_id=request.collection_id,
            )
        except ValueError as error:
            if str(error) == "similarity_confirmation_required":
                confirmation = self._metadata_selections.put(result)
                raise ControlFailure(
                    code="confirmation_required",
                    status=409,
                    details={"confirmation_token": confirmation, "kind": "similarity"},
                ) from None
            raise _metadata_error(error, "metadata_provider_unavailable") from None
        except ControlPortError:
            raise
        except Exception as error:
            raise _metadata_error(error, "metadata_provider_unavailable") from None
        return MetadataSelectionResult(
            item=self._projector.item_detail(outcome.item.id, locale),
            created=outcome.created,
        )

    async def import_manual(
        self, *, request: ManualImportRequest, confirmation_token: str | None = None
    ) -> ManualImportResult:
        return await invoke(
            lambda: self._import_manual(request, confirmation_token),
            fallback="manual_import_invalid",
        )

    def _import_manual(
        self, request: ManualImportRequest, confirmation_token: str | None
    ) -> ManualImportResult:
        if confirmation_token is not None:
            draft = self._consume_manual_draft(confirmation_token, operation="import")
            request = draft.request
            confirm_existing = True
        else:
            confirm_existing = False
        payload = request.document.model_dump(mode="json")
        try:
            outcome = self._manual_service().import_item(
                document=MetadataImportDocument.from_bytes(json.dumps(payload).encode("utf-8")),
                confirm_duplicate=confirm_existing,
                collection_id=request.collection_id,
            )
        except ValueError as error:
            if str(error) == "duplicate_confirmation_required" and not confirm_existing:
                return ManualImportResult(
                    confirmation_token=self._manual_drafts.put(
                        ManualDraft(operation="import", request=request)
                    )
                )
            raise _metadata_error(error, "manual_import_invalid") from None
        except ControlPortError:
            raise
        except Exception as error:
            raise _metadata_error(error, "manual_import_invalid") from None
        return ManualImportResult(
            item=self._projector.item_detail(outcome.item.id, request.document.locale),
            created=outcome.created,
        )

    async def edit_manual(
        self,
        *,
        item_id: str,
        document: ManualDocumentV1,
        confirmation_token: str | None = None,
    ) -> ManualImportResult:
        return await invoke(
            lambda: self._edit_manual(item_id, document, confirmation_token),
            fallback="manual_import_invalid",
        )

    def _edit_manual(
        self,
        item_id: str,
        document: ManualDocumentV1,
        confirmation_token: str | None,
    ) -> ManualImportResult:
        request = ManualImportRequest(document=document)
        editor_key = self._editor_key()
        if confirmation_token is None:
            item = self._queries.get_item(item_id)
            if (
                item is None
                or item.identity.provider_id != editor_key
                or document.external_id != item.identity.external_id
            ):
                raise ControlFailure(code="manual_item_not_found", status=404)
            return ManualImportResult(
                confirmation_token=self._manual_drafts.put(
                    ManualDraft(
                        operation="edit",
                        request=request,
                        item_id=item_id,
                        expected_current_revision_id=item.current_revision_id,
                    )
                )
            )
        draft = self._consume_manual_draft(confirmation_token, operation="edit")
        if draft.item_id != item_id or draft.expected_current_revision_id is None:
            raise ControlFailure(code="selection_expired", status=410)
        payload = draft.request.document.model_dump(mode="json")
        try:
            outcome = self._manual_service().edit_item(
                item_id=item_id,
                document=MetadataImportDocument.from_bytes(json.dumps(payload).encode("utf-8")),
                expected_current_revision_id=draft.expected_current_revision_id,
            )
        except (ControlFailure, ControlPortError):
            raise
        except Exception as error:
            raise _metadata_error(error, "manual_import_invalid") from None
        return ManualImportResult(
            item=self._projector.item_detail(outcome.item.id, draft.request.document.locale)
        )

    async def confirm_manual(self, *, token: str) -> ManualImportResult:
        return await invoke(lambda: self._confirm_manual(token), fallback="manual_import_invalid")

    def _confirm_manual(self, token: str) -> ManualImportResult:
        try:
            draft = self._manual_drafts.pop(token)
        except EphemeralTokenExpired:
            raise ControlFailure(code="selection_expired", status=410) from None
        continuation = self._manual_drafts.put(draft)
        if draft.operation == "import":
            return self._import_manual(draft.request, continuation)
        if draft.operation == "edit" and draft.item_id is not None:
            return self._edit_manual(draft.item_id, draft.request.document, continuation)
        raise ControlFailure(code="selection_expired", status=410)

    async def import_episodes(
        self, *, item_id: str, request: EpisodeImportRequest, locale: Locale
    ) -> MediaItemDetail:
        return await invoke(
            lambda: self._import_episodes(item_id, request, locale),
            fallback="manual_import_invalid",
        )

    def _import_episodes(
        self, item_id: str, request: EpisodeImportRequest, locale: Locale
    ) -> MediaItemDetail:
        current = self._queries.get_item(item_id)
        if current is None or current.current_revision_id is None:
            raise ControlFailure(code="manual_item_not_found", status=404)
        try:
            outcome = self._manual_service().import_episode_table(
                item_id=item_id,
                document=EpisodeTableDocument.from_bytes(request.csv.encode("utf-8")),
                expected_current_revision_id=current.current_revision_id,
            )
        except (ControlFailure, ControlPortError):
            raise
        except Exception as error:
            raise _metadata_error(error, "manual_import_invalid") from None
        return self._projector.item_detail(outcome.item.id, locale)

    def _manual_service(self) -> ManualCatalogService:
        editor_key = self._editor_key()
        try:
            return ManualCatalogService(
                query_port=self._queries,
                unit_of_work=self._uow,
                editor=self._modules.metadata_editor(editor_key),
                provider_id=editor_key,
                retention_policy=self._modules.retention_policy(editor_key),
                clock=self._clock,
            )
        except ControlPortError:
            raise
        except Exception as error:
            raise _metadata_error(error, "metadata_editor_unavailable") from None

    def _editor_key(self) -> str:
        values = self._modules.editor_ids()
        if len(values) != 1:
            raise ControlFailure(code="metadata_editor_unavailable", status=503)
        return values[0]

    def _consume_manual_draft(self, token: str, *, operation: str) -> ManualDraft:
        try:
            draft = self._manual_drafts.pop(token)
        except EphemeralTokenExpired:
            raise ControlFailure(code="selection_expired", status=410) from None
        if draft.operation != operation:
            raise ControlFailure(code="selection_expired", status=410)
        return draft


def _metadata_error(error: Exception, fallback: str) -> ControlPortError:
    code = getattr(error, "code", None)
    if not isinstance(code, str) and isinstance(error, ValueError):
        code = str(error)
    return ControlPortError(code if code in _METADATA_CODES else fallback)
