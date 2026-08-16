"""Compatibility composition for the core browser-control facade."""

from __future__ import annotations

from datetime import UTC, datetime

from media_finder_core.acquisition.persistence import (
    SqlAlchemyAcquisitionQueries,
    SqlAlchemyAcquisitionUnitOfWork,
)
from media_finder_core.catalog.persistence import (
    SqlAlchemyCatalogQueries,
    SqlAlchemyCatalogUnitOfWork,
)
from media_finder_core.control import (
    AcquisitionControlService,
    CatalogControlService,
    CatalogViewProjector,
    ControlFacade,
    DiagnosticsControlService,
    ManualDraft,
    MetadataControlService,
)
from media_finder_core.control.security import CursorCodec
from media_finder_core.platform import EphemeralCache
from media_finder_sdk import MetadataSearchResult as CoreMetadataSearchResult
from sqlalchemy.orm import Session, sessionmaker

from .control_adapters import (
    AcquisitionRuntimeAdapter,
    CatalogControlUnitOfWork,
    DiagnosticsRuntimeAdapter,
    MetadataCapabilitiesPort,
    MetadataRuntimeAdapter,
)
from .integration_runtime import RuntimeResolver
from .sdk.registration import StaticModuleRegistry

__all__ = ["BackendControlGateway", "CursorCodec"]


class BackendControlGateway(ControlFacade):
    """Assemble narrow adapters behind the portable core control facade."""

    def __init__(
        self,
        *,
        sessions: sessionmaker[Session],
        cursor_secret: bytes,
        runtime: RuntimeResolver | None = None,
        metadata_selections: EphemeralCache[CoreMetadataSearchResult] | None = None,
        manual_drafts: EphemeralCache[ManualDraft] | None = None,
        registry: StaticModuleRegistry,
        metadata_capabilities: MetadataCapabilitiesPort | None = None,
        build_version: str = "0.1.0",
    ) -> None:
        catalog_queries = SqlAlchemyCatalogQueries(sessions)
        catalog_uow = SqlAlchemyCatalogUnitOfWork(sessions)
        acquisition_queries = SqlAlchemyAcquisitionQueries(sessions)
        acquisition_uow = SqlAlchemyAcquisitionUnitOfWork(sessions)
        projector = CatalogViewProjector(
            catalog=catalog_queries,
            acquisitions=acquisition_queries,
        )
        metadata_modules = MetadataRuntimeAdapter(
            runtime=runtime,
            registry=registry,
            capabilities=metadata_capabilities,
        )
        acquisition_modules = AcquisitionRuntimeAdapter(runtime)
        super().__init__(
            catalog=CatalogControlService(
                query_port=catalog_queries,
                unit_of_work=CatalogControlUnitOfWork(catalog_uow),
                projector=projector,
                cursor_secret=cursor_secret,
                clock=lambda: datetime.now(UTC),
            ),
            metadata=MetadataControlService(
                query_port=catalog_queries,
                unit_of_work=catalog_uow,
                modules=metadata_modules,
                projector=projector,
                clock=lambda: datetime.now(UTC),
                metadata_selections=metadata_selections,
                manual_drafts=manual_drafts,
            ),
            acquisition=AcquisitionControlService(
                catalog_queries=catalog_queries,
                pinned_catalog=catalog_queries,
                acquisition_queries=acquisition_queries,
                acquisition_uow=acquisition_uow,
                modules=acquisition_modules,
                clock=lambda: datetime.now(UTC),
            ),
            diagnostics=DiagnosticsControlService(
                modules=DiagnosticsRuntimeAdapter(runtime=runtime, registry=registry),
                build_version=build_version,
            ),
        )
