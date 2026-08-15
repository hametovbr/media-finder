"""Catalog commands and invariants independent of persistence technology."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from .models import (
    CatalogIdentity,
    CollectionSnapshot,
    ItemResolution,
    MediaItemSnapshot,
    MetadataRevisionSnapshot,
    RevisionDraft,
)
from .ports import CatalogRepository


class CatalogCommands:
    def __init__(
        self,
        *,
        repository: CatalogRepository,
        clock: Callable[[], datetime],
    ) -> None:
        self._repository = repository
        self._clock = clock

    def create_collection(self, name: str) -> CollectionSnapshot:
        cleaned = name.strip()
        if not cleaned:
            raise ValueError("collection_name_required")
        return self._repository.add_collection(cleaned, self._clock())

    def archive_collection(self, collection_id: str) -> CollectionSnapshot:
        self._require_collection(collection_id)
        return self._repository.set_collection_archived(collection_id, self._clock())

    def restore_collection(self, collection_id: str) -> CollectionSnapshot:
        self._require_collection(collection_id)
        return self._repository.set_collection_archived(collection_id, None)

    def get_or_create_item(self, identity: CatalogIdentity) -> ItemResolution:
        existing = self._repository.find_item_by_identity(identity)
        if existing is not None:
            if existing.identity.media_kind is not identity.media_kind:
                raise ValueError("provider_identity_mismatch")
            return ItemResolution(item=existing, created=False)
        return ItemResolution(
            item=self._repository.add_item(identity, self._clock()),
            created=True,
        )

    def append_revision(self, item_id: str, draft: RevisionDraft) -> MetadataRevisionSnapshot:
        item = self._require_item(item_id)
        provenance = draft.normalized.provenance
        effective_provenance = draft.effective.provenance
        expected = item.identity
        if (
            draft.normalized.kind is not expected.media_kind
            or draft.effective.kind is not expected.media_kind
            or provenance.provider_id != expected.provider_id
            or effective_provenance.provider_id != expected.provider_id
            or provenance.external_id != expected.external_id
            or effective_provenance.external_id != expected.external_id
        ):
            raise ValueError("provider_identity_mismatch")
        return self._repository.append_revision(item_id, draft)

    def archive_item(self, item_id: str) -> MediaItemSnapshot:
        self._require_item(item_id)
        return self._repository.set_item_archived(item_id, self._clock())

    def restore_item(self, item_id: str) -> MediaItemSnapshot:
        self._require_item(item_id)
        return self._repository.set_item_archived(item_id, None)

    def move_item(self, item_id: str, collection_id: str | None) -> MediaItemSnapshot:
        self._require_item(item_id)
        if collection_id is not None:
            collection = self._require_collection(collection_id)
            if collection.archived_at is not None:
                raise ValueError("collection_unavailable")
        return self._repository.set_item_collection(item_id, collection_id)

    def _require_collection(self, collection_id: str) -> CollectionSnapshot:
        collection = self._repository.get_collection(collection_id)
        if collection is None:
            raise ValueError("collection_not_found")
        return collection

    def _require_item(self, item_id: str) -> MediaItemSnapshot:
        item = self._repository.get_item(item_id)
        if item is None:
            raise ValueError("media_item_not_found")
        return item


__all__ = ["CatalogCommands"]
