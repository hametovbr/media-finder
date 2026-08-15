"""Environment-owned runtime construction boundary for the browser UI."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from threading import RLock
from typing import Protocol

import httpx
from media_finder_core import ModuleRuntime
from media_finder_core.acquisition import ReleaseSelectionCache, ReleaseSelectionService
from media_finder_sdk import (
    CorrelationResult as CoreCorrelationResult,
)
from media_finder_sdk import (
    DownloadArtifact as CoreDownloadArtifact,
)
from media_finder_sdk import (
    DownloadClient as CoreDownloadClient,
)
from media_finder_sdk import (
    DownloadDestination as CoreDownloadDestination,
)
from media_finder_sdk import (
    ExportWarning as CoreExportWarning,
)
from media_finder_sdk import MagnetArtifact as CoreMagnetArtifact
from media_finder_sdk import (
    MediaKind as CoreMediaKind,
)
from media_finder_sdk import (
    MetadataEditor,
    MetadataIdentity,
    MetadataRetentionPolicy,
    MetadataSearchQuery,
    MetadataSearchResult,
    ModuleFailureCategory,
    ProviderPayload,
    ReleaseProviderRegistration,
    RetentionSubject,
    resolve_module_environment,
)
from media_finder_sdk import (
    MetadataProvider as CoreMetadataProvider,
)
from media_finder_sdk import ModuleError as CoreModuleError
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
from media_finder_sdk import (
    SubmissionResult as CoreSubmissionResult,
)
from media_finder_sdk import (
    TorrentArtifact as CoreTorrentArtifact,
)

from .models import DownloadClientInstance
from .sdk.errors import ModuleError as LegacyModuleError
from .sdk.protocols import DownloadClient, MetadataProvider
from .sdk.registration import (
    EnvironmentConfigurationError,
    IntegrationDescriptor,
    StaticModuleRegistry,
    resolve_environment,
)
from .sdk.settings import EnvReference
from .sdk.types import (
    Attribution,
    EnvironmentVariableSpec,
)
from .sdk.types import (
    CorrelationResult as LegacyCorrelationResult,
)
from .sdk.types import (
    DownloadArtifact as LegacyDownloadArtifact,
)
from .sdk.types import (
    MagnetArtifact as LegacyMagnetArtifact,
)
from .sdk.types import RetentionPolicy as LegacyRetentionPolicy
from .sdk.types import (
    SubmissionResult as LegacySubmissionResult,
)
from .sdk.types import (
    TorrentArtifact as LegacyTorrentArtifact,
)
from .system_clients import SYSTEM_QBITTORRENT_ID

type ReleaseRegistrationFactory = Callable[
    [Callable[[], httpx.Client]], ReleaseProviderRegistration
]
type ClientLoader = Callable[[DownloadClientInstance], DownloadClient]


@dataclass(frozen=True, slots=True)
class RuntimeResult[T]:
    value: T | None
    error_code: str | None = None
    missing_variables: tuple[str, ...] = ()


class RuntimeFactory(Protocol):
    def metadata_provider(self, key: str) -> RuntimeResult[MetadataProvider]: ...

    def prowlarr(self) -> RuntimeResult[ReleaseSelectionService]: ...

    def download_client(
        self, instance: DownloadClientInstance
    ) -> RuntimeResult[DownloadClient]: ...


class RuntimeLifecycle(Protocol):
    def close(self) -> None: ...


class DefaultRuntimeFactory:
    """Construct first-party integrations from one process-environment snapshot."""

    def __init__(
        self,
        *,
        http_client_factory: Callable[[], httpx.Client] = httpx.Client,
        registry: StaticModuleRegistry,
        release_registration_factory: ReleaseRegistrationFactory,
        environment: Mapping[str, str] | None = None,
        lifecycle: RuntimeLifecycle | None = None,
        module_runtime: ModuleRuntime | None = None,
    ) -> None:
        self._http_client_factory = http_client_factory
        self._environment = dict(os.environ if environment is None else environment)
        self._secret_resolver = self._resolve_environment_secret
        self._prowlarr: dict[tuple[str, str], ReleaseSelectionService] = {}
        self._metadata: dict[tuple[str, str], MetadataProvider] = {}
        self._download_clients: dict[tuple[str, str], DownloadClient] = {}
        self._http_clients: list[httpx.Client] = []
        self._registry = registry
        self._lifecycle = lifecycle
        self._module_runtime = module_runtime
        self._release_registration_factory = release_registration_factory
        release_manifest = release_registration_factory(http_client_factory).manifest
        self._release_integration = IntegrationDescriptor(
            key=release_manifest.module_id,
            version=release_manifest.module_version,
            environment=tuple(
                EnvironmentVariableSpec(
                    name=value.name,
                    required=value.required,
                    secret=value.secret,
                    description_key=value.description_key,
                )
                for value in release_manifest.environment
            ),
        )
        self._lock = RLock()
        self._closed = False

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            release_services = list(self._prowlarr.values())
            download_clients = list(self._download_clients.values())
            clients = self._http_clients
            self._http_clients = []
            self._prowlarr.clear()
            self._metadata.clear()
            self._download_clients.clear()
            lifecycle = self._lifecycle
            self._lifecycle = None
        first_error: BaseException | None = None
        for release_service in reversed(release_services):
            try:
                release_service.close()
            except BaseException as error:
                if first_error is None:
                    first_error = error
        for download_client in reversed(download_clients):
            try:
                self._close_module(download_client)
            except BaseException as error:
                if first_error is None:
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
    def release_integration(self) -> IntegrationDescriptor:
        return self._release_integration

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

    def prowlarr(self) -> RuntimeResult[ReleaseSelectionService]:
        with self._lock:
            if self._closed:
                return RuntimeResult(None, "integration_runtime_closed")
        owned_clients: list[httpx.Client] = []
        provider = None
        try:
            environment = resolve_environment(
                self._release_integration.environment, self._environment
            )
            key = ("environment", self._release_integration.key)
            with self._lock:
                existing = self._prowlarr.get(key)
            if existing is not None:
                return RuntimeResult(existing)
            registered = self._release_registration_factory(
                self._attempt_client_factory(owned_clients)
            )
            provider = registered.build(
                resolve_module_environment(registered.manifest, environment)
            )
            provider.validate()
            adapter = ReleaseSelectionService(
                provider=provider,
                cache=ReleaseSelectionCache(),
            )
            with self._lock:
                if self._closed:
                    existing = None
                    runtime_closed = True
                else:
                    runtime_closed = False
                    existing = self._prowlarr.get(key)
                if not runtime_closed and existing is None:
                    self._prowlarr[key] = adapter
                    return RuntimeResult(adapter)
            if runtime_closed:
                adapter.close()
                return RuntimeResult(None, "integration_runtime_closed")
            adapter.close()
            return RuntimeResult(existing)
        except EnvironmentConfigurationError as error:
            self._close_clients(owned_clients)
            return RuntimeResult(None, error.code, error.missing)
        except Exception:
            if provider is not None:
                provider.close()
            else:
                self._close_clients(owned_clients)
            with self._lock:
                if self._closed:
                    return RuntimeResult(None, "integration_runtime_closed")
            return RuntimeResult(None, "prowlarr_configuration_invalid")

    def download_client(self, instance: DownloadClientInstance) -> RuntimeResult[DownloadClient]:
        with self._lock:
            if self._closed:
                return RuntimeResult(None, "integration_runtime_closed")
        if instance.id != SYSTEM_QBITTORRENT_ID or not instance.system_owned:
            return RuntimeResult(None, "download_client_system_required")
        registration = self._registry.download_clients.get(instance.module_key)
        if registration is None:
            return RuntimeResult(None, "download_client_module_unknown")
        owned_clients: list[httpx.Client] = []
        client = None
        try:
            environment = resolve_environment(registration.environment, self._environment)
            cache_key = (registration.key, "environment")
            with self._lock:
                existing = self._download_clients.get(cache_key)
            if existing is not None:
                return RuntimeResult(existing)
            client = registration.build(
                environment,
                self._attempt_client_factory(owned_clients),
                self._secret_resolver,
            )
            client.validate_config()
            with self._lock:
                if self._closed:
                    existing = None
                    runtime_closed = True
                else:
                    runtime_closed = False
                    existing = self._download_clients.get(cache_key)
                if not runtime_closed and existing is None:
                    self._download_clients[cache_key] = client
                    if not callable(getattr(client, "close", None)):
                        self._http_clients.extend(owned_clients)
                    return RuntimeResult(client)
            if runtime_closed:
                self._close_module_or_clients(client, owned_clients)
                return RuntimeResult(None, "integration_runtime_closed")
            self._close_module_or_clients(client, owned_clients)
            return RuntimeResult(existing)
        except EnvironmentConfigurationError as error:
            self._close_clients(owned_clients)
            return RuntimeResult(None, error.code, error.missing)
        except Exception:
            if client is None:
                self._close_clients(owned_clients)
            else:
                self._close_module_or_clients(client, owned_clients)
            with self._lock:
                if self._closed:
                    return RuntimeResult(None, "integration_runtime_closed")
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
        factory: RuntimeFactory | None,
        providers: Mapping[str, MetadataProvider],
        prowlarr: ReleaseSelectionService | None,
        client_loader: ClientLoader | None,
        download_client_versions: Mapping[str, str] | None = None,
    ) -> None:
        self._factory = factory
        self._providers = dict(providers)
        self._prowlarr = prowlarr
        self._client_loader = client_loader
        self._download_client_versions = dict(download_client_versions or {})

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

    def prowlarr(self) -> RuntimeResult[ReleaseSelectionService]:
        if self._factory is None:
            return RuntimeResult(
                self._prowlarr,
                None if self._prowlarr is not None else "prowlarr_not_configured",
            )
        try:
            return self._factory.prowlarr()
        except Exception:
            return RuntimeResult(None, "prowlarr_configuration_invalid")

    def download_client(self, instance: DownloadClientInstance) -> RuntimeResult[DownloadClient]:
        if instance.id != SYSTEM_QBITTORRENT_ID or not instance.system_owned:
            return RuntimeResult(None, "download_client_system_required")
        try:
            if self._factory is not None:
                result = self._factory.download_client(instance)
            elif self._client_loader is not None:
                result = RuntimeResult(self._client_loader(instance))
            else:
                return RuntimeResult(None, "download_client_unavailable")
            return result
        except Exception:
            return RuntimeResult(None, "download_client_configuration_invalid")

    def core_download_client(
        self, instance: DownloadClientInstance
    ) -> RuntimeResult[CoreDownloadClient]:
        module_runtime = (
            getattr(self._factory, "module_runtime", None) if self._factory is not None else None
        )
        if isinstance(module_runtime, ModuleRuntime):
            try:
                return RuntimeResult(module_runtime.download_client(instance.module_key))
            except Exception:
                return RuntimeResult(None, "download_client_configuration_invalid")
        legacy = self.download_client(instance)
        return RuntimeResult(
            _CoreDownloadClientAdapter(legacy.value) if legacy.value is not None else None,
            legacy.error_code,
            legacy.missing_variables,
        )

    def download_client_version(self, instance: DownloadClientInstance) -> str | None:
        module_runtime = (
            getattr(self._factory, "module_runtime", None) if self._factory is not None else None
        )
        if isinstance(module_runtime, ModuleRuntime):
            registration = module_runtime.registry.download.get(instance.module_key)
            if registration is not None:
                return registration.manifest.module_version
        return self._download_client_versions.get(instance.module_key)

    def provider_ready(self, key: str) -> bool:
        return self.metadata_provider(key).value is not None

    def prowlarr_ready(self) -> bool:
        return self.prowlarr().value is not None

    def client_ready(self, instance: DownloadClientInstance) -> bool:
        result = self.download_client(instance)
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


class _CoreDownloadClientAdapter:
    """Translate the temporary server client surface to the public SDK capability."""

    def __init__(self, client: DownloadClient) -> None:
        self._client = client

    def validate(self) -> None:
        self._client.validate_config()

    def list_destinations(self) -> tuple[CoreDownloadDestination, ...]:
        return tuple(
            CoreDownloadDestination.model_validate(value.model_dump(mode="json"))
            for value in self._client.list_destinations()
        )

    def submit(
        self,
        artifact: CoreDownloadArtifact,
        destination: str,
        correlation: str,
    ) -> CoreSubmissionResult:
        legacy_artifact: LegacyDownloadArtifact
        if isinstance(artifact, CoreMagnetArtifact):
            legacy_artifact = LegacyMagnetArtifact(uri=artifact.uri)
        elif isinstance(artifact, CoreTorrentArtifact):
            legacy_artifact = LegacyTorrentArtifact(content=artifact.content())
        else:  # pragma: no cover - the SDK union is closed
            raise ValueError("download_artifact_unsupported")
        try:
            value: LegacySubmissionResult = self._client.submit(
                legacy_artifact,
                destination,
                correlation,
            )
        except LegacyModuleError as error:
            raise _core_module_error(error.code) from None
        return CoreSubmissionResult.model_validate(value.model_dump(mode="json"))

    def find_by_correlation(self, correlation: str) -> CoreCorrelationResult:
        try:
            value: LegacyCorrelationResult = self._client.find_by_correlation(correlation)
        except LegacyModuleError as error:
            raise _core_module_error(error.code) from None
        return CoreCorrelationResult.model_validate(value.model_dump(mode="json"))

    def close(self) -> None:
        return None


def _core_module_error(code: str) -> CoreModuleError:
    return CoreModuleError(
        category=(
            ModuleFailureCategory.TIMEOUT
            if code == "submission_timeout"
            else ModuleFailureCategory.UNAVAILABLE
        ),
        code=code,
    )


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
