"""Environment-owned runtime construction boundary for the browser UI."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from threading import RLock
from typing import Protocol

import httpx
from media_finder_sdk import ReleaseProviderRegistration, resolve_module_environment

from .acquisition import ClientLoader
from .models import DownloadClientInstance
from .release_selection import ReleaseSelectionCache, ReleaseSelectionService
from .sdk.protocols import DownloadClient, MetadataProvider
from .sdk.registration import (
    EnvironmentConfigurationError,
    IntegrationDescriptor,
    StaticModuleRegistry,
    resolve_environment,
)
from .sdk.settings import EnvReference
from .sdk.types import Attribution, EnvironmentVariableSpec
from .system_clients import SYSTEM_QBITTORRENT_ID

type ReleaseRegistrationFactory = Callable[
    [Callable[[], httpx.Client]], ReleaseProviderRegistration
]


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
        self._release_registration_factory = release_registration_factory
        release_manifest = release_registration_factory(http_client_factory).manifest
        self._release_integration = IntegrationDescriptor(
            key=release_manifest.module_id,
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
            adapter = ReleaseSelectionService(provider, ReleaseSelectionCache())
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
    ) -> None:
        self._factory = factory
        self._providers = dict(providers)
        self._prowlarr = prowlarr
        self._client_loader = client_loader

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

    def metadata_providers(self) -> dict[str, MetadataProvider]:
        configured: dict[str, MetadataProvider] = {}
        for key in self._providers:
            result = self.metadata_provider(key)
            if result.value is not None:
                configured[key] = result.value
        return configured

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
