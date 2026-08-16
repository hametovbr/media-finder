"""Read-only acquisition application services."""

from __future__ import annotations

from .models import AcquisitionSnapshot
from .ports import AcquisitionQueryPort


class AcquisitionQueries:
    def __init__(self, *, query_port: AcquisitionQueryPort) -> None:
        self._queries = query_port

    def get(self, acquisition_id: str) -> AcquisitionSnapshot:
        value = self._queries.get(acquisition_id)
        if value is None:
            raise ValueError("acquisition_not_found")
        return value

    def pending_after_startup(self) -> tuple[AcquisitionSnapshot, ...]:
        return self._queries.pending()

    def for_media_item(
        self, media_item_id: str, *, limit: int = 50
    ) -> tuple[AcquisitionSnapshot, ...]:
        if limit < 1 or limit > 100:
            raise ValueError("acquisition_page_limit_invalid")
        return self._queries.for_media_item(media_item_id, limit=limit)


__all__ = ["AcquisitionQueries"]
