"""Read-only catalog application service."""

from __future__ import annotations

from datetime import datetime

from .models import (
    CatalogIdentity,
    CatalogPage,
    CollectionSnapshot,
    MediaItemSnapshot,
    MetadataRevisionSnapshot,
)
from .ports import CatalogQueryPort


class CatalogQueries:
    def __init__(self, *, query_port: CatalogQueryPort) -> None:
        self._queries = query_port

    def get_item(self, item_id: str) -> MediaItemSnapshot | None:
        return self._queries.get_item(item_id)

    def find_exact(self, identity: CatalogIdentity) -> MediaItemSnapshot | None:
        return self._queries.find_item_by_identity(identity)

    def list_revisions(self, item_id: str) -> tuple[MetadataRevisionSnapshot, ...]:
        return self._queries.list_revisions(item_id)

    def get_revision(self, revision_id: str) -> MetadataRevisionSnapshot | None:
        return self._queries.get_revision(revision_id)

    def retention_candidates(self, now: datetime) -> tuple[MetadataRevisionSnapshot, ...]:
        return self._queries.retention_candidates(now)

    def current_revision(self, item_id: str) -> MetadataRevisionSnapshot | None:
        item = self._queries.get_item(item_id)
        if item is None or item.current_revision_id is None:
            return None
        return next(
            (
                revision
                for revision in reversed(self._queries.list_revisions(item_id))
                if revision.id == item.current_revision_id
            ),
            None,
        )

    def list_collections(
        self,
        *,
        archived: bool = False,
        limit: int = 50,
        after: tuple[str, str] | None = None,
    ) -> CatalogPage[CollectionSnapshot]:
        _validate_limit(limit)
        return self._queries.page_collections(archived=archived, limit=limit, after=after)

    def list_items(
        self,
        *,
        archived: bool = False,
        collection_id: str | None = None,
        uncategorized: bool = False,
        limit: int = 50,
        after: tuple[str, str] | None = None,
    ) -> CatalogPage[MediaItemSnapshot]:
        _validate_limit(limit)
        return self._queries.page_items(
            archived=archived,
            collection_id=collection_id,
            uncategorized=uncategorized,
            limit=limit,
            after=after,
        )

    def find_similar(
        self,
        *,
        title: str,
        year: int | None,
        excluding_provider_id: str,
    ) -> tuple[MediaItemSnapshot, ...]:
        return self._queries.find_similar(
            normalized_title=title.casefold(),
            year=year,
            excluding_provider_id=excluding_provider_id,
        )


def _validate_limit(limit: int) -> None:
    if not 1 <= limit <= 100:
        raise ValueError("catalog_query_limit_invalid")


__all__ = ["CatalogQueries"]
