"""Application ports for acquisition commands and queries."""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime
from typing import Protocol

from .models import AcquisitionDraft, AcquisitionResolution, AcquisitionSnapshot, AcquisitionStatus


class AcquisitionRepository(Protocol):
    def find_by_idempotency(self, key: str) -> AcquisitionSnapshot | None: ...
    def get(self, acquisition_id: str) -> AcquisitionSnapshot | None: ...
    def add_pending(self, draft: AcquisitionDraft) -> AcquisitionSnapshot: ...
    def create_pending_if_absent(self, draft: AcquisitionDraft) -> AcquisitionResolution: ...
    def transition(
        self,
        acquisition_id: str,
        *,
        expected_status: AcquisitionStatus,
        status: AcquisitionStatus,
        external_task_id: str | None,
        failure_code: str | None,
        updated_at: datetime,
    ) -> AcquisitionSnapshot: ...
    def pending(self) -> tuple[AcquisitionSnapshot, ...]: ...
    def for_media_item(
        self, media_item_id: str, *, limit: int
    ) -> tuple[AcquisitionSnapshot, ...]: ...


class AcquisitionQueryPort(Protocol):
    def find_by_idempotency(self, key: str) -> AcquisitionSnapshot | None: ...
    def get(self, acquisition_id: str) -> AcquisitionSnapshot | None: ...
    def pending(self) -> tuple[AcquisitionSnapshot, ...]: ...
    def for_media_item(
        self, media_item_id: str, *, limit: int
    ) -> tuple[AcquisitionSnapshot, ...]: ...


class AcquisitionUnitOfWork(Protocol):
    def write(self) -> AbstractContextManager[AcquisitionRepository]: ...


class PinnedCatalogReadPort(Protocol):
    def has_pinned_revision(self, media_item_id: str, metadata_revision_id: str) -> bool: ...


__all__ = [
    "AcquisitionQueryPort",
    "AcquisitionRepository",
    "AcquisitionUnitOfWork",
    "PinnedCatalogReadPort",
]
