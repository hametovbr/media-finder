"""Narrow server adapters for framework-neutral core control ports."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from functools import partial
from typing import Literal

from media_finder_core import ModuleRuntime
from media_finder_core.acquisition import ModuleVersionSnapshot, ReleaseSelectionService
from media_finder_core.catalog import CatalogRepository, CatalogUnitOfWork
from media_finder_core.control import (
    AcquisitionControlModules,
    AttributionSnapshot,
    ControlPortError,
    DiagnosticModuleSnapshot,
    DiagnosticsControlModules,
    MetadataControlModules,
    MetadataModuleDescriptor,
)
from media_finder_sdk import (
    DownloadClient,
    MetadataEditor,
    MetadataProvider,
    MetadataRetentionPolicy,
    ModuleManifest,
)
from media_finder_sdk import (
    StaticModuleRegistry as TypedModuleRegistry,
)
from sqlalchemy.exc import IntegrityError

__all__ = [
    "AcquisitionRuntimeAdapter",
    "CatalogControlUnitOfWork",
    "DiagnosticsRuntimeAdapter",
    "MetadataRuntimeAdapter",
]

_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_-]{0,199}$")
_DIAGNOSTIC_CODE_TRANSLATIONS = {
    ("metadata_provider", "module_environment_missing"): "integration_environment_missing",
    (
        "metadata_provider",
        "metadata_provider_unavailable",
    ): "metadata_provider_configuration_invalid",
}


class CatalogControlUnitOfWork:
    """Translate a database uniqueness violation at the collection command boundary."""

    def __init__(self, unit_of_work: CatalogUnitOfWork) -> None:
        self._unit_of_work = unit_of_work

    @contextmanager
    def write(self) -> Iterator[CatalogRepository]:
        try:
            with self._unit_of_work.write() as repository:
                yield repository
        except IntegrityError:
            raise ControlPortError("collection_name_conflict") from None

    def savepoint(self):  # type: ignore[no-untyped-def]
        return self._unit_of_work.savepoint()


class MetadataRuntimeAdapter(MetadataControlModules):
    """Expose typed metadata registrations through the core control port."""

    def __init__(self, *, runtime: ModuleRuntime, registry: TypedModuleRegistry) -> None:
        self._runtime = runtime
        self._registry = registry

    def provider_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._registry.metadata))

    def editor_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                module_id
                for module_id, registration in self._registry.metadata.items()
                if registration.editor is not None
            )
        )

    def descriptors(self) -> tuple[MetadataModuleDescriptor, ...]:
        values: list[MetadataModuleDescriptor] = []
        for module_id, registration in sorted(self._registry.metadata.items()):
            try:
                self._runtime.metadata_provider(module_id)
                ready = True
            except Exception:
                ready = False
            values.append(
                MetadataModuleDescriptor(
                    module_id=module_id,
                    name_key=registration.manifest.name_key,
                    capabilities=registration.manifest.capabilities,
                    ready=ready,
                )
            )
        return tuple(values)

    def metadata_provider(self, module_id: str) -> MetadataProvider:
        try:
            return self._runtime.metadata_provider(module_id)
        except Exception as error:
            raise _port_error(error, "metadata_provider_unavailable") from None

    def metadata_editor(self, module_id: str) -> MetadataEditor:
        try:
            return self._runtime.metadata_editor(module_id)
        except Exception as error:
            raise _port_error(error, "metadata_editor_unavailable") from None

    def retention_policy(self, module_id: str) -> MetadataRetentionPolicy:
        try:
            return self._runtime.retention_policy(module_id)
        except Exception as error:
            raise _port_error(error, "metadata_provider_unavailable") from None


class AcquisitionRuntimeAdapter(AcquisitionControlModules):
    """Expose selected typed release/download modules through the control port."""

    def __init__(
        self,
        *,
        runtime: ModuleRuntime,
        release_selections: ReleaseSelectionService,
        release_manifest: ModuleManifest,
        download_manifest: ModuleManifest,
    ) -> None:
        self._runtime = runtime
        self._release_selections = release_selections
        self._release_manifest = release_manifest
        self._download_manifest = download_manifest

    def release_selections(self) -> ReleaseSelectionService:
        return self._release_selections

    def download_client(self) -> DownloadClient:
        try:
            return self._runtime.download_client(self._download_manifest.module_id)
        except Exception as error:
            raise _port_error(error, "download_client_unavailable") from None

    def release_module(self) -> ModuleVersionSnapshot:
        return _module_snapshot(self._release_manifest)

    def download_module(self) -> ModuleVersionSnapshot:
        return _module_snapshot(self._download_manifest)


class DiagnosticsRuntimeAdapter(DiagnosticsControlModules):
    """Project typed manifests, runtime readiness, and safe attribution values."""

    def __init__(
        self,
        *,
        runtime: ModuleRuntime,
        registry: TypedModuleRegistry,
        environment: Mapping[str, str],
        release_manifest: ModuleManifest,
        download_manifest: ModuleManifest,
        attribution_notices: Mapping[str, str],
    ) -> None:
        self._runtime = runtime
        self._registry = registry
        self._environment = dict(environment)
        self._release_manifest = release_manifest
        self._download_manifest = download_manifest
        self._attribution_notices = dict(attribution_notices)

    def diagnostic_modules(self) -> tuple[DiagnosticModuleSnapshot, ...]:
        values = [
            self._diagnostic(
                manifest=registration.manifest,
                kind="metadata_provider",
                resolve=partial(self._runtime.metadata_provider, module_id),
                fallback="metadata_provider_unavailable",
            )
            for module_id, registration in sorted(self._registry.metadata.items())
        ]
        values.append(
            self._diagnostic(
                manifest=self._release_manifest,
                kind="release_search",
                resolve=lambda: self._runtime.release_provider(self._release_manifest.module_id),
                fallback="release_provider_unavailable",
            )
        )
        values.append(
            self._diagnostic(
                manifest=self._download_manifest,
                kind="download_client",
                resolve=lambda: self._runtime.download_client(self._download_manifest.module_id),
                fallback="download_client_unavailable",
            )
        )
        return tuple(values)

    def environment_is_set(self, name: str) -> bool:
        value = self._environment.get(name)
        return isinstance(value, str) and bool(value.strip())

    def attributions(self) -> tuple[AttributionSnapshot, ...]:
        values: list[AttributionSnapshot] = []
        for registration in self._registry.metadata.values():
            manifest = registration.manifest
            attribution = manifest.attribution
            if attribution is None or any(
                declaration.required and not self.environment_is_set(declaration.name)
                for declaration in manifest.environment
            ):
                continue
            values.append(
                AttributionSnapshot(
                    provider_id=manifest.module_id,
                    notice=self._attribution_notices.get(
                        attribution.notice_key, attribution.notice_key
                    ),
                    url=str(attribution.url) if attribution.url is not None else None,
                )
            )
        return tuple(values)

    def _diagnostic(
        self,
        *,
        manifest: ModuleManifest,
        kind: Literal["metadata_provider", "download_client", "release_search"],
        resolve: Callable[[], object],
        fallback: str,
    ) -> DiagnosticModuleSnapshot:
        error_code: str | None = None
        try:
            resolve()
            ready = True
        except Exception as error:
            ready = False
            internal_code = _safe_error_code(error, fallback)
            error_code = _DIAGNOSTIC_CODE_TRANSLATIONS.get(
                (kind, internal_code),
                internal_code,
            )
        return DiagnosticModuleSnapshot(
            module_id=manifest.module_id,
            kind=kind,
            declarations=manifest.environment,
            ready=ready,
            error_code=error_code,
        )


def _port_error(error: Exception, fallback: str) -> ControlPortError:
    return ControlPortError(_safe_error_code(error, fallback))


def _safe_error_code(error: Exception, fallback: str) -> str:
    code = getattr(error, "code", None)
    if not isinstance(code, str) and isinstance(error, ValueError):
        candidate = str(error)
        code = candidate if _SAFE_CODE.fullmatch(candidate) else None
    return code or fallback


def _module_snapshot(manifest: ModuleManifest) -> ModuleVersionSnapshot:
    return ModuleVersionSnapshot(
        module_id=manifest.module_id,
        module_version=manifest.module_version,
    )
