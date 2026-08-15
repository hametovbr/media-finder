"""Environment-owned runtime construction boundary for the browser UI."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from threading import RLock
from typing import Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from .acquisition import ClientLoader
from .models import DownloadClientInstance
from .modules.registry import FIRST_PARTY_MODULES
from .prowlarr import HttpxProwlarrTransport, ProwlarrAdapter, SearchResultCache
from .sdk.protocols import DownloadClient, MetadataProvider
from .sdk.registration import (
    EnvironmentConfigurationError,
    IntegrationDescriptor,
    StaticModuleRegistry,
    resolve_environment,
)
from .sdk.settings import EnvReference, validate_service_base_url
from .sdk.types import Attribution, EnvironmentVariableSpec
from .system_clients import SYSTEM_QBITTORRENT_ID

PROWLARR_INTEGRATION = IntegrationDescriptor(
    key="prowlarr",
    environment=(
        EnvironmentVariableSpec(
            name="PROWLARR_URL",
            required=True,
            secret=False,
            description_key="integration.prowlarr.environment.url",
        ),
        EnvironmentVariableSpec(
            name="PROWLARR_API_KEY",
            required=True,
            secret=True,
            description_key="integration.prowlarr.environment.api_key",
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class RuntimeResult[T]:
    value: T | None
    error_code: str | None = None
    missing_variables: tuple[str, ...] = ()


class RuntimeFactory(Protocol):
    def metadata_provider(self, key: str) -> RuntimeResult[MetadataProvider]: ...

    def prowlarr(self) -> RuntimeResult[ProwlarrAdapter]: ...

    def download_client(
        self, instance: DownloadClientInstance
    ) -> RuntimeResult[DownloadClient]: ...


class ProwlarrSettings(BaseModel):
    """Typed core integration schema; secret values remain environment references."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    base_url: HttpUrl = Field(title="Base URL")
    api_key_ref: str = Field(title="API key environment reference")

    @field_validator("base_url")
    @classmethod
    def safe_origin(cls, value: HttpUrl) -> HttpUrl:
        try:
            validate_service_base_url(str(value), error_code="prowlarr_base_url_invalid")
        except ValueError:
            raise ValueError("prowlarr_base_url_invalid") from None
        return value

    @field_validator("api_key_ref")
    @classmethod
    def environment_reference(cls, value: str) -> str:
        return EnvReference(value=value).value


class DefaultRuntimeFactory:
    """Construct first-party integrations from one process-environment snapshot."""

    def __init__(
        self,
        *,
        http_client_factory: Callable[[], httpx.Client] = httpx.Client,
        registry: StaticModuleRegistry = FIRST_PARTY_MODULES,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self._http_client_factory = http_client_factory
        self._environment = dict(os.environ if environment is None else environment)
        self._secret_resolver = self._resolve_environment_secret
        self._prowlarr: dict[tuple[str, str], ProwlarrAdapter] = {}
        self._metadata: dict[tuple[str, str], MetadataProvider] = {}
        self._download_clients: dict[tuple[str, str], DownloadClient] = {}
        self._http_clients: list[httpx.Client] = []
        self._registry = registry
        self._lock = RLock()
        self._closed = False

    def close(self) -> None:
        with self._lock:
            self._closed = True
            clients = self._http_clients
            self._http_clients = []
            self._prowlarr.clear()
            self._metadata.clear()
            self._download_clients.clear()
        self._close_clients(clients)

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
            return RuntimeResult(None, "metadata_provider_configuration_invalid")

    def prowlarr(self) -> RuntimeResult[ProwlarrAdapter]:
        with self._lock:
            if self._closed:
                return RuntimeResult(None, "integration_runtime_closed")
        owned_clients: list[httpx.Client] = []
        try:
            environment = resolve_environment(PROWLARR_INTEGRATION.environment, self._environment)
            parsed = ProwlarrSettings(
                base_url=HttpUrl(environment["PROWLARR_URL"]),
                api_key_ref="env:PROWLARR_API_KEY",
            )
            key = ("environment", "prowlarr")
            with self._lock:
                existing = self._prowlarr.get(key)
            if existing is not None:
                return RuntimeResult(existing)
            client = self._attempt_client_factory(owned_clients)()
            transport = HttpxProwlarrTransport(
                str(parsed.base_url),
                parsed.api_key_ref,
                self._secret_resolver,
                client,
            )
            transport.validate()
            adapter = ProwlarrAdapter(transport, SearchResultCache())
            with self._lock:
                if self._closed:
                    existing = None
                    runtime_closed = True
                else:
                    runtime_closed = False
                    existing = self._prowlarr.get(key)
                if not runtime_closed and existing is None:
                    self._prowlarr[key] = adapter
                    self._http_clients.extend(owned_clients)
                    return RuntimeResult(adapter)
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
                    self._http_clients.extend(owned_clients)
                    return RuntimeResult(client)
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
        prowlarr: ProwlarrAdapter | None,
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

    def prowlarr(self) -> RuntimeResult[ProwlarrAdapter]:
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
