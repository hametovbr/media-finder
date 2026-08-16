"""Compatibility composition for the core browser-control facade."""

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
    LegacyAcquisitionRuntimeAdapter,
    LegacyDiagnosticsRuntimeAdapter,
    LegacyMetadataRuntimeAdapter,
    MetadataCapabilitiesPort,
    MetadataRuntimeAdapter,
)
from .integration_runtime import RuntimeResolver
from .legacy_sdk.registration import StaticModuleRegistry as LegacyModuleRegistry

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
        registry: TypedModuleRegistry | LegacyModuleRegistry,
        module_runtime: ModuleRuntime | None = None,
        release_selections: ReleaseSelectionService | None = None,
        release_manifest: ModuleManifest | None = None,
        download_manifest: ModuleManifest | None = None,
        environment: Mapping[str, str] | None = None,
        attribution_notices: Mapping[str, str] | None = None,
        runtime: RuntimeResolver | None = None,
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
        metadata_modules: MetadataControlModules
        acquisition_modules: AcquisitionControlModules
        diagnostics_modules: DiagnosticsControlModules
        if module_runtime is not None:
            if not isinstance(registry, TypedModuleRegistry):
                raise TypeError("typed_module_registry_required")
            if release_selections is None or release_manifest is None or download_manifest is None:
                raise TypeError("typed_acquisition_resources_required")
            metadata_modules = MetadataRuntimeAdapter(
                runtime=module_runtime,
                registry=registry,
            )
            acquisition_modules = AcquisitionRuntimeAdapter(
                runtime=module_runtime,
                release_selections=release_selections,
                release_manifest=release_manifest,
                download_manifest=download_manifest,
            )
            diagnostics_modules = DiagnosticsRuntimeAdapter(
                runtime=module_runtime,
                registry=registry,
                environment=environment or {},
                release_manifest=release_manifest,
                download_manifest=download_manifest,
                attribution_notices=attribution_notices or {},
            )
        else:
            if not isinstance(registry, LegacyModuleRegistry):
                raise TypeError("legacy_module_registry_required")
            metadata_modules = LegacyMetadataRuntimeAdapter(
                runtime=runtime,
                registry=registry,
                capabilities=metadata_capabilities,
            )
            acquisition_modules = LegacyAcquisitionRuntimeAdapter(runtime)
            diagnostics_modules = LegacyDiagnosticsRuntimeAdapter(
                runtime=runtime,
                registry=registry,
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
