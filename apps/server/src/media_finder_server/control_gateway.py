"""Server composition for the core browser-control facade."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from media_finder_core import ModuleRuntime
from media_finder_core.acquisition import ReleaseSelectionService
from media_finder_core.acquisition.persistence import (
    SqlAlchemyAcquisitionQueries,
    SqlAlchemyAcquisitionUnitOfWork,
)
from media_finder_core.catalog.persistence import (
    SqlAlchemyCatalogQueries,
    SqlAlchemyCatalogUnitOfWork,
)
from media_finder_core.control import (
    AcquisitionControlModules,
    AcquisitionControlService,
    CatalogControlService,
    CatalogViewProjector,
    ControlFacade,
    DiagnosticsControlModules,
    DiagnosticsControlService,
    ManualDraft,
    MetadataControlModules,
    MetadataControlService,
)
from media_finder_core.control.security import CursorCodec
from media_finder_core.platform import EphemeralCache
from media_finder_sdk import (
    MetadataSearchResult as CoreMetadataSearchResult,
)
from media_finder_sdk import (
    ModuleManifest,
)
from media_finder_sdk import (
    StaticModuleRegistry as TypedModuleRegistry,
)
from sqlalchemy.orm import Session, sessionmaker

from .control_adapters import (
    AcquisitionRuntimeAdapter,
    CatalogControlUnitOfWork,
    DiagnosticsRuntimeAdapter,
    MetadataRuntimeAdapter,
)

__all__ = ["BackendControlGateway", "CursorCodec"]


class BackendControlGateway(ControlFacade):
    """Assemble narrow adapters behind the portable core control facade."""

    def __init__(
        self,
        *,
        sessions: sessionmaker[Session],
        cursor_secret: bytes,
        metadata_selections: EphemeralCache[CoreMetadataSearchResult],
        manual_drafts: EphemeralCache[ManualDraft],
        registry: TypedModuleRegistry,
        module_runtime: ModuleRuntime,
        release_selections: ReleaseSelectionService,
        release_manifest: ModuleManifest,
        download_manifest: ModuleManifest,
        environment: Mapping[str, str] | None = None,
        attribution_notices: Mapping[str, str] | None = None,
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
        metadata_modules: MetadataControlModules = MetadataRuntimeAdapter(
            runtime=module_runtime,
            registry=registry,
        )
        acquisition_modules: AcquisitionControlModules = AcquisitionRuntimeAdapter(
            runtime=module_runtime,
            release_selections=release_selections,
            release_manifest=release_manifest,
            download_manifest=download_manifest,
        )
        diagnostics_modules: DiagnosticsControlModules = DiagnosticsRuntimeAdapter(
            runtime=module_runtime,
            registry=registry,
            environment=environment or {},
            release_manifest=release_manifest,
            download_manifest=download_manifest,
            attribution_notices=attribution_notices or {},
        )
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
                modules=diagnostics_modules,
                build_version=build_version,
            ),
        )
