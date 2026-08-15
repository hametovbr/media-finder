"""Framework-free catalog persistence and query ports."""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime
from typing import Protocol

from .models import (
    CatalogIdentity,
    CatalogPage,
    CollectionSnapshot,
    MediaItemSnapshot,
    MetadataRevisionSnapshot,
    RevisionDraft,
)


class CatalogRepository(Protocol):
    def add_collection(self, name: str, created_at: datetime) -> CollectionSnapshot: ...

    def get_collection(self, collection_id: str) -> CollectionSnapshot | None: ...

    def set_collection_archived(
        self, collection_id: str, archived_at: datetime | None
    ) -> CollectionSnapshot: ...

    def find_item_by_identity(self, identity: CatalogIdentity) -> MediaItemSnapshot | None: ...

    def add_item(self, identity: CatalogIdentity, created_at: datetime) -> MediaItemSnapshot: ...

    def get_item(self, item_id: str) -> MediaItemSnapshot | None: ...

    def append_revision(self, item_id: str, draft: RevisionDraft) -> MetadataRevisionSnapshot: ...

    def get_revision(self, revision_id: str) -> MetadataRevisionSnapshot | None: ...

    def list_revisions(self, item_id: str) -> tuple[MetadataRevisionSnapshot, ...]: ...

    def find_similar(
        self,
        *,
        normalized_title: str,
        year: int | None,
        excluding_provider_id: str,
    ) -> tuple[MediaItemSnapshot, ...]: ...

    def purge_revision(self, revision_id: str, attempted_at: datetime) -> None: ...

    def record_retention_refreshed(self, revision_id: str, attempted_at: datetime) -> None: ...

    def record_retention_failure(
        self, revision_id: str, code: str, attempted_at: datetime
    ) -> None: ...

    def set_item_archived(
        self, item_id: str, archived_at: datetime | None
    ) -> MediaItemSnapshot: ...

    def set_item_collection(self, item_id: str, collection_id: str | None) -> MediaItemSnapshot: ...


class CatalogQueryPort(Protocol):
    def get_collection(self, collection_id: str) -> CollectionSnapshot | None: ...

    def get_item(self, item_id: str) -> MediaItemSnapshot | None: ...

    def find_item_by_identity(self, identity: CatalogIdentity) -> MediaItemSnapshot | None: ...

    def list_revisions(self, item_id: str) -> tuple[MetadataRevisionSnapshot, ...]: ...

    def get_revision(self, revision_id: str) -> MetadataRevisionSnapshot | None: ...

    def retention_candidates(self, now: datetime) -> tuple[MetadataRevisionSnapshot, ...]: ...

    def page_collections(
        self, *, archived: bool, limit: int, after: tuple[str, str] | None
    ) -> CatalogPage[CollectionSnapshot]: ...

    def page_items(
        self,
        *,
        archived: bool,
        collection_id: str | None,
        uncategorized: bool,
        limit: int,
        after: tuple[str, str] | None,
    ) -> CatalogPage[MediaItemSnapshot]: ...

    def find_similar(
        self,
        *,
        normalized_title: str,
        year: int | None,
        excluding_provider_id: str,
    ) -> tuple[MediaItemSnapshot, ...]: ...


class CatalogUnitOfWork(Protocol):
    def write(self) -> AbstractContextManager[CatalogRepository]: ...

    def savepoint(self) -> AbstractContextManager[CatalogRepository]: ...


__all__ = ["CatalogQueryPort", "CatalogRepository", "CatalogUnitOfWork"]
