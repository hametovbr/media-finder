"""Narrow server adapters for framework-neutral core control ports."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from functools import partial
from typing import Literal, Protocol

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
    EnvironmentVariableSpec,
    MetadataEditor,
    MetadataProvider,
    MetadataRetentionPolicy,
    ModuleManifest,
)
from media_finder_sdk import (
    StaticModuleRegistry as TypedModuleRegistry,
)
from sqlalchemy.exc import IntegrityError

from .integration_runtime import LegacyMetadataCapabilities, RuntimeResolver
from .legacy_sdk.registration import StaticModuleRegistry as LegacyModuleRegistry
from .legacy_sdk.types import EnvironmentVariableSpec as LegacyEnvironmentVariableSpec

__all__ = [
    "AcquisitionRuntimeAdapter",
    "CatalogControlUnitOfWork",
    "DiagnosticsRuntimeAdapter",
    "LegacyAcquisitionRuntimeAdapter",
    "LegacyDiagnosticsRuntimeAdapter",
    "LegacyMetadataRuntimeAdapter",
    "MetadataCapabilitiesPort",
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


class MetadataCapabilitiesPort(Protocol):
    def metadata_provider(self, module_id: str) -> MetadataProvider: ...

    def metadata_editor(self, module_id: str) -> MetadataEditor: ...

    def retention_policy(self, module_id: str) -> MetadataRetentionPolicy: ...


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


class LegacyMetadataRuntimeAdapter(MetadataControlModules):
    """Expose only metadata capabilities and safe descriptors to core control."""

    def __init__(
        self,
        *,
        runtime: RuntimeResolver | None,
        registry: LegacyModuleRegistry,
        capabilities: MetadataCapabilitiesPort | None,
    ) -> None:
        self._runtime = runtime
        self._registry = registry
        self._capabilities = capabilities or (
            LegacyMetadataCapabilities(runtime) if runtime is not None else None
        )

    def provider_ids(self) -> tuple[str, ...]:
        if self._capabilities is None:
            raise ControlPortError("integration_runtime_unavailable")
        if isinstance(self._capabilities, ModuleRuntime):
            return tuple(sorted(self._capabilities.registry.metadata))
        if self._runtime is None:
            return ()
        return tuple(sorted(self._runtime.supported_providers))

    def editor_ids(self) -> tuple[str, ...]:
        if isinstance(self._capabilities, ModuleRuntime):
            return tuple(
                sorted(
                    module_id
                    for module_id, registration in self._capabilities.registry.metadata.items()
                    if registration.editor is not None
                )
            )
        if self._runtime is None:
            return ()
        return tuple(
            sorted(
                module_id
                for module_id, provider in self._runtime.supported_providers.items()
                if isinstance(provider, MetadataEditor)
            )
        )

    def descriptors(self) -> tuple[MetadataModuleDescriptor, ...]:
        runtime = self._require_runtime()
        values: list[MetadataModuleDescriptor] = []
        for module_id in sorted(self._registry.metadata_providers):
            prototype = runtime.supported_providers.get(module_id)
            result = runtime.metadata_provider(module_id)
            provider = result.value or prototype
            if provider is None:
                continue
            values.append(
                MetadataModuleDescriptor(
                    module_id=module_id,
                    name_key=provider.manifest.name_key,
                    capabilities=provider.manifest.capabilities,
                    ready=result.value is not None,
                )
            )
        return tuple(values)

    def metadata_provider(self, module_id: str) -> MetadataProvider:
        capabilities = self._require_capabilities()
        try:
            return capabilities.metadata_provider(module_id)
        except Exception as error:
            raise _port_error(error, "metadata_provider_unavailable") from None

    def metadata_editor(self, module_id: str) -> MetadataEditor:
        capabilities = self._require_capabilities()
        try:
            return capabilities.metadata_editor(module_id)
        except Exception as error:
            raise _port_error(error, "metadata_editor_unavailable") from None

    def retention_policy(self, module_id: str) -> MetadataRetentionPolicy:
        capabilities = self._require_capabilities()
        try:
            return capabilities.retention_policy(module_id)
        except Exception as error:
            raise _port_error(error, "metadata_provider_unavailable") from None

    def _require_runtime(self) -> RuntimeResolver:
        if self._runtime is None:
            raise ControlPortError("integration_runtime_unavailable")
        return self._runtime

    def _require_capabilities(self) -> MetadataCapabilitiesPort:
        if self._capabilities is None:
            raise ControlPortError("integration_runtime_unavailable")
        return self._capabilities


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


class LegacyAcquisitionRuntimeAdapter(AcquisitionControlModules):
    """Expose only selected release/download capabilities and module identities."""

    def __init__(self, runtime: RuntimeResolver | None) -> None:
        self._runtime = runtime

    def release_selections(self) -> ReleaseSelectionService:
        result = self._require_runtime().release_selections()
        if result.value is None:
            raise ControlPortError(result.error_code or "release_provider_unavailable")
        return result.value

    def download_client(self) -> DownloadClient:
        result = self._require_runtime().selected_download_client()
        if result.value is None:
            raise ControlPortError(result.error_code or "download_client_unavailable")
        return result.value

    def release_module(self) -> ModuleVersionSnapshot:
        try:
            manifest = self._require_runtime().release_manifest
            return ModuleVersionSnapshot(
                module_id=manifest.module_id,
                module_version=manifest.module_version,
            )
        except ControlPortError:
            raise
        except Exception as error:
            raise _port_error(error, "release_provider_unavailable") from None

    def download_module(self) -> ModuleVersionSnapshot:
        try:
            manifest = self._require_runtime().download_manifest
            return ModuleVersionSnapshot(
                module_id=manifest.module_id,
                module_version=manifest.module_version,
            )
        except ControlPortError:
            raise
        except Exception as error:
            raise _port_error(error, "download_client_unavailable") from None

    def _require_runtime(self) -> RuntimeResolver:
        if self._runtime is None:
            raise ControlPortError("integration_runtime_unavailable")
        return self._runtime


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


class LegacyDiagnosticsRuntimeAdapter(DiagnosticsControlModules):
    """Read only value-free declarations, readiness, and attribution data."""

    def __init__(
        self,
        *,
        runtime: RuntimeResolver | None,
        registry: LegacyModuleRegistry,
    ) -> None:
        self._runtime = runtime
        self._registry = registry

    def diagnostic_modules(self) -> tuple[DiagnosticModuleSnapshot, ...]:
        runtime = self._require_runtime()
        values: list[DiagnosticModuleSnapshot] = []
        for module_id, registration in sorted(self._registry.metadata_providers.items()):
            result = runtime.metadata_provider(module_id)
            values.append(
                DiagnosticModuleSnapshot(
                    module_id=module_id,
                    kind="metadata_provider",
                    declarations=_environment_specs(registration.environment),
                    ready=result.value is not None,
                    error_code=result.error_code,
                )
            )
        release = runtime.release_selections()
        release_manifest = runtime.release_manifest
        values.append(
            DiagnosticModuleSnapshot(
                module_id=release_manifest.module_id,
                kind="release_search",
                declarations=release_manifest.environment,
                ready=release.value is not None,
                error_code=release.error_code,
            )
        )
        download = runtime.selected_download_client()
        download_manifest = runtime.download_manifest
        values.append(
            DiagnosticModuleSnapshot(
                module_id=download_manifest.module_id,
                kind="download_client",
                declarations=download_manifest.environment,
                ready=download.value is not None,
                error_code=download.error_code,
            )
        )
        return tuple(values)

    def environment_is_set(self, name: str) -> bool:
        return self._require_runtime().environment_is_set(name)

    def attributions(self) -> tuple[AttributionSnapshot, ...]:
        runtime = self._require_runtime()
        values = [factory() for factory in self._registry.static_attributions]
        values.extend(runtime.configured_provider_attributions())
        return tuple(
            AttributionSnapshot(
                provider_id=value.provider_key,
                notice=value.notice,
                url=str(value.url) if value.url is not None else None,
            )
            for value in values
        )

    def _require_runtime(self) -> RuntimeResolver:
        if self._runtime is None:
            raise ControlPortError("integration_runtime_unavailable")
        return self._runtime


def _environment_specs(
    values: tuple[LegacyEnvironmentVariableSpec, ...],
) -> tuple[EnvironmentVariableSpec, ...]:
    return tuple(
        EnvironmentVariableSpec(
            name=value.name,
            required=value.required,
            secret=value.secret,
            description_key=value.description_key,
        )
        for value in values
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
