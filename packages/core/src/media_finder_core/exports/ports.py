"""Framework-free read ports consumed by processor export use cases."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .metadata import ExportRevisionSnapshot


class CatalogExportReadPort(Protocol):
    def current_revision_id(self, media_item_id: str) -> str | None: ...

    def revision(self, revision_id: str) -> ExportRevisionSnapshot | None: ...


class AcquisitionExportReadPort(Protocol):
    def pinned_revision_id(self, acquisition_id: str) -> str | None: ...


__all__ = ["AcquisitionExportReadPort", "CatalogExportReadPort"]
