"""Environment-owned runtime construction boundary for the browser UI."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from threading import RLock
from typing import Protocol, runtime_checkable

import httpx
from media_finder_core import ModuleRuntime
from media_finder_core.acquisition import ReleaseSelectionService
from media_finder_sdk import DownloadClient as CoreDownloadClient
from media_finder_sdk import (
    ExportWarning as CoreExportWarning,
)
from media_finder_sdk import (
    MediaKind as CoreMediaKind,
)
from media_finder_sdk import (
    MetadataEditor,
    MetadataIdentity,
    MetadataRetentionPolicy,
    MetadataSearchQuery,
    MetadataSearchResult,
    ModuleManifest,
    ProviderPayload,
    RetentionSubject,
)
from media_finder_sdk import (
    MetadataProvider as CoreMetadataProvider,
)
from media_finder_sdk import (
    ModuleError as CoreModuleError,
)
from media_finder_sdk import (
    NormalizedMetadata as CoreNormalizedMetadata,
)
from media_finder_sdk import (
    RetentionAction as CoreRetentionAction,
)
from media_finder_sdk import (
    RetentionActionKind as CoreRetentionActionKind,
)
from media_finder_sdk import (
    RetentionPolicy as CoreRetentionPolicy,
)

from .sdk.protocols import MetadataProvider
from .sdk.registration import (
    EnvironmentConfigurationError,
    StaticModuleRegistry,
    resolve_environment,
)
from .sdk.settings import EnvReference
from .sdk.types import (
    Attribution,
)
from .sdk.types import RetentionPolicy as LegacyRetentionPolicy


@dataclass(frozen=True, slots=True)
class RuntimeResult[T]:
    value: T | None
    error_code: str | None = None
    missing_variables: tuple[str, ...] = ()


class RuntimeFactory(Protocol):
    def metadata_provider(self, key: str) -> RuntimeResult[MetadataProvider]: ...


@runtime_checkable
class AcquisitionModuleAccess(Protocol):
    @property
    def release_manifest(self) -> ModuleManifest: ...

    @property
    def download_manifest(self) -> ModuleManifest: ...

    def release_selections(self) -> RuntimeResult[ReleaseSelectionService]: ...

    def selected_download_client(self) -> RuntimeResult[CoreDownloadClient]: ...


class RuntimeLifecycle(Protocol):
    def close(self) -> None: ...


class DefaultRuntimeFactory:
    """Construct first-party integrations from one process-environment snapshot."""

    def __init__(
        self,
        *,
        http_client_factory: Callable[[], httpx.Client] = httpx.Client,
        registry: StaticModuleRegistry,
        environment: Mapping[str, str] | None = None,
        lifecycle: RuntimeLifecycle | None = None,
        module_runtime: ModuleRuntime | None = None,
        release_manifest: ModuleManifest | None = None,
        download_manifest: ModuleManifest | None = None,
        release_selections: ReleaseSelectionService | None = None,
    ) -> None:
        self._http_client_factory = http_client_factory
        self._environment = dict(os.environ if environment is None else environment)
        self._secret_resolver = self._resolve_environment_secret
        self._metadata: dict[tuple[str, str], MetadataProvider] = {}
        self._http_clients: list[httpx.Client] = []
        self._registry = registry
        self._lifecycle = lifecycle
        self._module_runtime = module_runtime
        self._release_manifest = release_manifest
        self._download_manifest = download_manifest
        self._release_selection_service = release_selections
        self._lock = RLock()
        self._closed = False

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            clients = self._http_clients
            self._http_clients = []
            self._metadata.clear()
            release_selections = self._release_selection_service
            self._release_selection_service = None
            lifecycle = self._lifecycle
            self._lifecycle = None
        first_error: BaseException | None = None
        if release_selections is not None:
            try:
                release_selections.close()
            except BaseException as error:
                first_error = error
        try:
            self._close_clients(clients)
        except BaseException as error:
            if first_error is None:
                first_error = error
        if lifecycle is not None:
            try:
                lifecycle.close()
            except BaseException as error:
                if first_error is None:
                    first_error = error
        if first_error is not None:
            raise first_error

    @property
    def release_manifest(self) -> ModuleManifest:
        if self._release_manifest is None:
            raise ValueError("release_provider_unavailable")
        return self._release_manifest

    @property
    def download_manifest(self) -> ModuleManifest:
        if self._download_manifest is None:
            raise ValueError("download_client_unavailable")
        return self._download_manifest

    @property
    def registry(self) -> StaticModuleRegistry:
        return self._registry

    @property
    def module_runtime(self) -> ModuleRuntime | None:
        return self._module_runtime

    def metadata_provider(self, key: str) -> RuntimeResult[MetadataProvider]:
        with self._lock:
            if self._closed:
                return RuntimeResult(None, "integration_runtime_closed")
        registration = self._registry.metadata_providers.get(key)
        if registration is None:
            return RuntimeResult(None, "metadata_provider_not_found")
        owned_clients: list[httpx.Client] = []
        try:
            environment = resolve_environment(registration.environment, self._environment)
            cache_key = (key, "environment")
            with self._lock:
                existing = self._metadata.get(cache_key)
            if existing is not None:
                return RuntimeResult(existing)
            provider = registration.build(
                environment,
                self._attempt_client_factory(owned_clients),
                self._secret_resolver,
            )
            provider.validate_config()
            with self._lock:
                if self._closed:
                    existing = None
                    runtime_closed = True
                else:
                    runtime_closed = False
                    existing = self._metadata.get(cache_key)
                if not runtime_closed and existing is None:
                    self._metadata[cache_key] = provider
                    self._http_clients.extend(owned_clients)
                    return RuntimeResult(provider)
            if runtime_closed:
                self._close_clients(owned_clients)
                return RuntimeResult(None, "integration_runtime_closed")
            self._close_clients(owned_clients)
            return RuntimeResult(existing)
        except EnvironmentConfigurationError as error:
            self._close_clients(owned_clients)
            return RuntimeResult(None, error.code, error.missing)
        except Exception:
            self._close_clients(owned_clients)
            with self._lock:
                if self._closed:
                    return RuntimeResult(None, "integration_runtime_closed")
            return RuntimeResult(None, "metadata_provider_configuration_invalid")

    def release_selections(self) -> RuntimeResult[ReleaseSelectionService]:
        with self._lock:
            if self._closed:
                return RuntimeResult(None, "integration_runtime_closed")
        service = self._release_selection_service
        if service is None:
            return RuntimeResult(None, "release_provider_unavailable")
        try:
            # Validate the borrowed capability before exposing the cache.
            if self._module_runtime is None:
                return RuntimeResult(None, "release_provider_unavailable")
            self._module_runtime.release_provider(self.release_manifest.module_id)
            return RuntimeResult(service)
        except CoreModuleError as error:
            return _runtime_failure(error)
        except Exception:
            return RuntimeResult(None, "release_provider_configuration_invalid")

    def selected_download_client(self) -> RuntimeResult[CoreDownloadClient]:
        with self._lock:
            if self._closed:
                return RuntimeResult(None, "integration_runtime_closed")
        if self._module_runtime is None:
            return RuntimeResult(None, "download_client_unavailable")
        try:
            return RuntimeResult(
                self._module_runtime.download_client(self.download_manifest.module_id)
            )
        except CoreModuleError as error:
            return _runtime_failure(error)
        except Exception:
            return RuntimeResult(None, "download_client_configuration_invalid")

    def _attempt_client_factory(
        self, owned_clients: list[httpx.Client]
    ) -> Callable[[], httpx.Client]:
        def create() -> httpx.Client:
            client = self._http_client_factory()
            owned_clients.append(client)
            return client

        return create

    @staticmethod
    def _close_clients(clients: list[httpx.Client]) -> None:
        for client in clients:
            client.close()

    @staticmethod
    def _close_module(instance: object) -> bool:
        close = getattr(instance, "close", None)
        if not callable(close):
            return False
        close()
        return True

    @classmethod
    def _close_module_or_clients(
        cls,
        instance: object,
        clients: list[httpx.Client],
    ) -> None:
        if not cls._close_module(instance):
            cls._close_clients(clients)

    def _resolve_environment_secret(self, reference: str) -> str:
        variable_name = EnvReference(value=reference).variable_name
        return self._environment[variable_name]

    def environment_is_set(self, name: str) -> bool:
        """Expose presence only; never return environment values to the UI."""

        return bool(self._environment.get(name, "").strip())

    def metadata_provider_environment_configured(self, key: str) -> bool:
        """Check required declarations without constructing or probing a provider."""

        registration = self._registry.metadata_providers.get(key)
        if registration is None:
            return False
        return all(
            not declaration.required or self.environment_is_set(declaration.name)
            for declaration in registration.environment
        )


class RuntimeResolver:
    """Resolve every live integration from one environment-owned runtime source."""

    def __init__(
        self,
        *,
        module_runtime: ModuleRuntime | None = None,
        factory: RuntimeFactory | None = None,
        providers: Mapping[str, MetadataProvider] | None = None,
        acquisition: AcquisitionModuleAccess | None = None,
    ) -> None:
        self._factory = factory
        self._providers = dict(providers or {})
        inherited_runtime = getattr(factory, "module_runtime", None)
        self._module_runtime = module_runtime or (
            inherited_runtime if isinstance(inherited_runtime, ModuleRuntime) else None
        )
        self._acquisition = acquisition or (
            factory if isinstance(factory, AcquisitionModuleAccess) else None
        )

    @property
    def supported_providers(self) -> Mapping[str, MetadataProvider]:
        return self._providers

    def metadata_provider(self, key: str) -> RuntimeResult[MetadataProvider]:
        prototype = self._providers.get(key)
        if prototype is None:
            return RuntimeResult(None, "metadata_provider_not_found")
        if self._factory is None:
            return RuntimeResult(prototype)
        try:
            return self._factory.metadata_provider(key)
        except Exception:
            return RuntimeResult(None, "metadata_provider_configuration_invalid")

    def configured_provider_attributions(self) -> list[Attribution]:
        """Return attribution for configured modules without probing live services."""

        attributions: list[Attribution] = []
        for key, provider in self._providers.items():
            configured = True
            if self._factory is not None:
                probe = getattr(self._factory, "metadata_provider_environment_configured", None)
                configured = bool(probe(key)) if callable(probe) else True
            if configured:
                attributions.append(provider.attribution())
        return attributions

    @property
    def release_manifest(self) -> ModuleManifest:
        if self._acquisition is not None:
            return self._acquisition.release_manifest
        runtime = self._require_module_runtime()
        registrations = tuple(runtime.registry.release.values())
        if len(registrations) != 1:
            raise ValueError("release_provider_selection_invalid")
        return registrations[0].manifest

    @property
    def download_manifest(self) -> ModuleManifest:
        if self._acquisition is not None:
            return self._acquisition.download_manifest
        runtime = self._require_module_runtime()
        registrations = tuple(runtime.registry.download.values())
        if len(registrations) != 1:
            raise ValueError("download_client_selection_invalid")
        return registrations[0].manifest

    def release_selections(self) -> RuntimeResult[ReleaseSelectionService]:
        if self._acquisition is not None:
            return self._acquisition.release_selections()
        return RuntimeResult(None, "release_provider_unavailable")

    def selected_download_client(self) -> RuntimeResult[CoreDownloadClient]:
        if self._acquisition is not None:
            return self._acquisition.selected_download_client()
        try:
            runtime = self._require_module_runtime()
            return RuntimeResult(runtime.download_client(self.download_manifest.module_id))
        except Exception:
            return RuntimeResult(None, "download_client_configuration_invalid")

    def provider_ready(self, key: str) -> bool:
        return self.metadata_provider(key).value is not None

    def release_provider_ready(self) -> bool:
        return self.release_selections().value is not None

    def download_client_ready(self) -> bool:
        result = self.selected_download_client()
        if result.value is None:
            return False
        try:
            result.value.list_destinations()
        except Exception:
            return False
        return True

    def environment_is_set(self, name: str) -> bool:
        if self._factory is None:
            return False
        probe = getattr(self._factory, "environment_is_set", None)
        return bool(probe(name)) if callable(probe) else False

    def _require_module_runtime(self) -> ModuleRuntime:
        if self._module_runtime is None:
            raise ValueError("module_runtime_unavailable")
        return self._module_runtime


def _runtime_failure[T](error: CoreModuleError) -> RuntimeResult[T]:
    missing = error.safe_details.get("missing_names", ())
    missing_names = (
        tuple(value for value in missing if isinstance(value, str))
        if isinstance(missing, tuple)
        else ()
    )
    return RuntimeResult(None, error.code, missing_names)


class LegacyMetadataCapabilities:
    """Shape legacy test/runtime providers into the typed core capability ports."""

    def __init__(self, runtime: RuntimeResolver) -> None:
        self._runtime = runtime

    def metadata_provider(self, module_id: str) -> CoreMetadataProvider:
        result = self._runtime.metadata_provider(module_id)
        if result.value is None:
            raise ValueError(result.error_code or "metadata_provider_unavailable")
        return _LegacyCoreMetadataProvider(result.value)

    def metadata_editor(self, module_id: str) -> MetadataEditor:
        result = self._runtime.metadata_provider(module_id)
        if result.value is None:
            raise ValueError(result.error_code or "metadata_provider_unavailable")
        if not isinstance(result.value, MetadataEditor):
            raise ValueError("metadata_editor_unavailable")
        return result.value

    def retention_policy(self, module_id: str) -> MetadataRetentionPolicy:
        provider = self._runtime.supported_providers.get(module_id)
        if provider is None:
            raise ValueError("metadata_provider_unavailable")
        return _LegacyCoreRetentionPolicy(provider)


class _LegacyCoreMetadataProvider:
    def __init__(self, provider: MetadataProvider) -> None:
        self._provider = provider

    def validate(self) -> None:
        self._provider.validate_config()

    def search(self, query: MetadataSearchQuery) -> tuple[MetadataSearchResult, ...]:
        return tuple(
            MetadataSearchResult(
                provider_id=value.provider_key,
                external_id=value.external_id,
                media_kind=CoreMediaKind(value.kind.value),
                title=value.title,
                year=value.year,
                locale=value.locale,
            )
            for value in self._provider.search(query.query, query.locale)
        )

    def fetch(self, identity: MetadataIdentity) -> ProviderPayload:
        return ProviderPayload(
            data=self._provider.fetch(
                identity.media_kind.value,
                identity.external_id,
                identity.locale,
            )
        )

    def normalize(
        self, payload: ProviderPayload, identity: MetadataIdentity
    ) -> CoreNormalizedMetadata:
        legacy = self._provider.normalize(
            dict(payload.data),
            identity.media_kind.value,
            identity.external_id,
            identity.locale,
        )
        serialized = legacy.model_dump(mode="json")
        provenance = serialized.get("provenance")
        if not isinstance(provenance, dict):
            raise ValueError("metadata_provenance_invalid")
        provenance["provider_id"] = provenance.pop("provider_key")
        return CoreNormalizedMetadata.model_validate(serialized)

    def close(self) -> None:
        return None


class _LegacyCoreRetentionPolicy:
    def __init__(self, provider: MetadataProvider) -> None:
        self._provider = provider

    def retention_for(self, created_at: datetime) -> CoreRetentionPolicy:
        value = self._provider.retention_for(created_at)
        return CoreRetentionPolicy(
            refresh_after=value.refresh_after,
            expires_at=value.expires_at,
        )

    def plan(self, subject: RetentionSubject, now: datetime) -> CoreRetentionAction:
        value = self._provider.plan_retention(
            self._legacy_policy(subject.policy),
            now,
        )
        return CoreRetentionAction(
            kind=CoreRetentionActionKind(value.kind.value),
            mandatory=value.mandatory,
        )

    def export_warning(
        self, policy: CoreRetentionPolicy, now: datetime
    ) -> CoreExportWarning | None:
        warning = self._provider.export_warning(self._legacy_policy(policy), now)
        return (
            CoreExportWarning.model_validate(warning.model_dump(mode="json"))
            if warning is not None
            else None
        )

    def close(self) -> None:
        return None

    @staticmethod
    def _legacy_policy(policy: CoreRetentionPolicy) -> LegacyRetentionPolicy:
        return LegacyRetentionPolicy(
            refresh_after=policy.refresh_after,
            expires_at=policy.expires_at,
        )
