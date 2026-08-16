"""Metadata-editor orchestration independent of any concrete module."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from media_finder_sdk import (
    EpisodeTableDocument,
    MetadataEditor,
    MetadataImportDocument,
    MetadataRetentionPolicy,
)

from .commands import CatalogCommands
from .models import ItemResolution, MediaItemSnapshot, MetadataRevisionSnapshot
from .ports import CatalogQueryPort, CatalogUnitOfWork
from .validation import (
    catalog_identity,
    revision_draft,
    validate_edit_result,
    validate_retention_policy,
)


class ManualCatalogService:
    def __init__(
        self,
        *,
        query_port: CatalogQueryPort,
        unit_of_work: CatalogUnitOfWork,
        editor: MetadataEditor,
        provider_id: str,
        retention_policy: MetadataRetentionPolicy,
        clock: Callable[[], datetime],
    ) -> None:
        self._queries = query_port
        self._uow = unit_of_work
        self._editor = editor
        self._provider_id = provider_id
        self._retention = retention_policy
        self._clock = clock

    def import_item(
        self,
        *,
        document: MetadataImportDocument,
        confirm_duplicate: bool = False,
        collection_id: str | None = None,
    ) -> ItemResolution:
        result = validate_edit_result(self._editor.import_document(document))
        identity = catalog_identity(result.identity)
        existing = self._queries.find_item_by_identity(identity)
        if existing is not None and not confirm_duplicate:
            raise ValueError("duplicate_confirmation_required")
        return self._persist_edit_result(
            result=result,
            expected_item_id=existing.id if existing is not None else None,
            expected_current_revision_id=None,
            collection_id=collection_id,
        )

    def edit_item(
        self,
        *,
        item_id: str,
        document: MetadataImportDocument,
        expected_current_revision_id: str,
    ) -> ItemResolution:
        item = self._require_item(item_id)
        result = validate_edit_result(self._editor.import_document(document))
        if catalog_identity(result.identity) != item.identity:
            raise ValueError("provider_identity_mismatch")
        return self._persist_edit_result(
            result=result,
            expected_item_id=item.id,
            expected_current_revision_id=expected_current_revision_id,
            collection_id=None,
        )

    def import_episode_table(
        self,
        *,
        item_id: str,
        document: EpisodeTableDocument,
        expected_current_revision_id: str,
    ) -> ItemResolution:
        item = self._require_item(item_id)
        current = self._require_current_revision(item.id)
        if current.id != expected_current_revision_id:
            raise ValueError("catalog_current_revision_changed")
        if current.effective is None:
            raise ValueError("manual_metadata_missing")
        result = validate_edit_result(self._editor.merge_episode_table(current.effective, document))
        if catalog_identity(result.identity) != item.identity:
            raise ValueError("provider_identity_mismatch")
        return self._persist_edit_result(
            result=result,
            expected_item_id=item.id,
            expected_current_revision_id=expected_current_revision_id,
            collection_id=None,
        )

    def _persist_edit_result(
        self,
        *,
        result: object,
        expected_item_id: str | None,
        expected_current_revision_id: str | None,
        collection_id: str | None,
    ) -> ItemResolution:
        validated = validate_edit_result(result)
        if validated.identity.provider_id != self._provider_id:
            raise ValueError("provider_identity_mismatch")
        now = self._clock()
        draft = revision_draft(
            raw_payload=validated.raw_payload,
            normalized=validated.metadata,
            retention=validate_retention_policy(self._retention.retention_for(now)),
            created_at=now,
        )
        with self._uow.write() as repository:
            commands = CatalogCommands(repository=repository, clock=self._clock)
            resolution = commands.get_or_create_item(catalog_identity(validated.identity))
            if expected_item_id is None and not resolution.created:
                raise ValueError("duplicate_confirmation_required")
            if expected_item_id is not None and resolution.item.id != expected_item_id:
                raise ValueError("provider_identity_mismatch")
            commands.append_revision(
                resolution.item.id,
                draft,
                expected_current_revision_id=expected_current_revision_id,
            )
            if collection_id is not None:
                commands.move_item(resolution.item.id, collection_id)
            persisted = repository.get_item(resolution.item.id)
            if persisted is None:  # pragma: no cover - a repository contract violation
                raise RuntimeError("catalog_item_persistence_failed")
            return ItemResolution(item=persisted, created=resolution.created)

    def _require_item(self, item_id: str) -> MediaItemSnapshot:
        item = self._queries.get_item(item_id)
        if item is None:
            raise ValueError("media_item_not_found")
        return item

    def _require_current_revision(self, item_id: str) -> MetadataRevisionSnapshot:
        item = self._require_item(item_id)
        if item.current_revision_id is None:
            raise ValueError("manual_metadata_missing")
        revision = self._queries.get_revision(item.current_revision_id)
        if revision is None:
            raise ValueError("manual_metadata_missing")
        return revision


__all__ = ["ManualCatalogService"]
