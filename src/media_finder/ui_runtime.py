"""Persisted-settings runtime construction boundary for the browser UI."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from threading import RLock
from typing import Protocol, cast

import httpx
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator
from sqlalchemy.orm import Session, sessionmaker

from .acquisition import ClientLoader
from .config import resolve_env_reference
from .models import AppSetting, DownloadClientInstance
from .modules.registry import FIRST_PARTY_MODULES
from .prowlarr import HttpxProwlarrTransport, ProwlarrAdapter, SearchResultCache
from .sdk.protocols import DownloadClient, MetadataProvider
from .sdk.registration import StaticModuleRegistry
from .sdk.settings import EnvReference, validate_service_base_url
from .sdk.types import Attribution


@dataclass(frozen=True, slots=True)
class RuntimeResult[T]:
    value: T | None
    error_code: str | None = None


class RuntimeFactory(Protocol):
    def metadata_provider(
        self, key: str, config: Mapping[str, object]
    ) -> RuntimeResult[MetadataProvider]: ...

    def prowlarr(self, config: Mapping[str, object]) -> RuntimeResult[ProwlarrAdapter]: ...

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


def _resolve_secret(reference: str) -> str:
    return resolve_env_reference(EnvReference(value=reference)).get_secret_value()


class DefaultRuntimeFactory:
    """Construct first-party integrations from persisted safe configuration."""

    def __init__(
        self,
        *,
        http_client_factory: Callable[[], httpx.Client] = httpx.Client,
        secret_resolver: Callable[[str], str] = _resolve_secret,
        registry: StaticModuleRegistry = FIRST_PARTY_MODULES,
    ) -> None:
        self._http_client_factory = http_client_factory
        self._secret_resolver = secret_resolver
        self._prowlarr: dict[tuple[str, str], ProwlarrAdapter] = {}
        self._metadata: dict[tuple[str, str], MetadataProvider] = {}
        self._download_clients: dict[tuple[str, str], DownloadClient] = {}
        self._http_clients: list[httpx.Client] = []
        self._registry = registry
        self._lock = RLock()

    def close(self) -> None:
        with self._lock:
            clients = self._http_clients
            self._http_clients = []
            self._prowlarr.clear()
            self._metadata.clear()
            self._download_clients.clear()
        self._close_clients(clients)

    def metadata_provider(
        self, key: str, config: Mapping[str, object]
    ) -> RuntimeResult[MetadataProvider]:
        registration = self._registry.metadata_providers.get(key)
        if registration is None:
            return RuntimeResult(None, "metadata_provider_not_found")
        owned_clients: list[httpx.Client] = []
        try:
            parsed = registration.config_model.model_validate(config)
            cache_key = (key, json.dumps(parsed.model_dump(mode="json"), sort_keys=True))
            with self._lock:
                existing = self._metadata.get(cache_key)
            if existing is not None:
                return RuntimeResult(existing)
            provider = registration.build(
                parsed.model_dump(mode="json"),
                self._attempt_client_factory(owned_clients),
                self._secret_resolver,
            )
            provider.validate_config()
            with self._lock:
                existing = self._metadata.get(cache_key)
                if existing is None:
                    self._metadata[cache_key] = provider
                    self._http_clients.extend(owned_clients)
                    return RuntimeResult(provider)
            self._close_clients(owned_clients)
            return RuntimeResult(existing)
        except Exception:
            self._close_clients(owned_clients)
            return RuntimeResult(None, "metadata_provider_configuration_invalid")

    def prowlarr(self, config: Mapping[str, object]) -> RuntimeResult[ProwlarrAdapter]:
        owned_clients: list[httpx.Client] = []
        try:
            parsed = ProwlarrSettings.model_validate(config)
            key = (str(parsed.base_url), parsed.api_key_ref)
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
                existing = self._prowlarr.get(key)
                if existing is None:
                    self._prowlarr[key] = adapter
                    self._http_clients.extend(owned_clients)
                    return RuntimeResult(adapter)
            self._close_clients(owned_clients)
            return RuntimeResult(existing)
        except Exception:
            self._close_clients(owned_clients)
            return RuntimeResult(None, "prowlarr_configuration_invalid")

    def download_client(self, instance: DownloadClientInstance) -> RuntimeResult[DownloadClient]:
        registration = self._registry.download_clients.get(instance.module_key)
        if registration is None:
            return RuntimeResult(None, "download_client_module_unknown")
        owned_clients: list[httpx.Client] = []
        try:
            parsed = registration.config_model.model_validate(instance.config_payload)
            cache_key = (
                instance.id,
                json.dumps(parsed.model_dump(mode="json"), sort_keys=True),
            )
            with self._lock:
                existing = self._download_clients.get(cache_key)
            if existing is not None:
                return RuntimeResult(existing)
            client = registration.build(
                parsed.model_dump(mode="json"),
                self._attempt_client_factory(owned_clients),
                self._secret_resolver,
            )
            client.validate_config()
            with self._lock:
                existing = self._download_clients.get(cache_key)
                if existing is None:
                    self._download_clients[cache_key] = client
                    self._http_clients.extend(owned_clients)
                    return RuntimeResult(client)
            self._close_clients(owned_clients)
            return RuntimeResult(existing)
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


class RuntimeResolver:
    """Resolve every live integration from the same persisted configuration source."""

    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        factory: RuntimeFactory | None,
        providers: Mapping[str, MetadataProvider],
        prowlarr: ProwlarrAdapter | None,
        client_loader: ClientLoader | None,
    ) -> None:
        self._sessions = sessions
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
        payload = self._setting(f"metadata_provider:{key}")
        if payload is None:
            try:
                payload = prototype.config_model.model_validate({}).model_dump(mode="json")
            except Exception:
                return RuntimeResult(None, "metadata_provider_not_configured")
        try:
            return self._factory.metadata_provider(key, payload)
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
            configured = (
                self._factory is None or self._setting(f"metadata_provider:{key}") is not None
            )
            if not configured:
                try:
                    provider.config_model.model_validate({})
                    configured = True
                except Exception:
                    pass
            if configured:
                attributions.append(provider.attribution())
        return attributions

    def prowlarr(self) -> RuntimeResult[ProwlarrAdapter]:
        if self._factory is None:
            return RuntimeResult(
                self._prowlarr,
                None if self._prowlarr is not None else "prowlarr_not_configured",
            )
        payload = self._setting("prowlarr")
        if payload is None:
            return RuntimeResult(None, "prowlarr_not_configured")
        try:
            return self._factory.prowlarr(payload)
        except Exception:
            return RuntimeResult(None, "prowlarr_configuration_invalid")

    def download_client(self, instance: DownloadClientInstance) -> RuntimeResult[DownloadClient]:
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

    def _setting(self, key: str) -> dict[str, object] | None:
        with self._sessions() as database:
            setting = database.get(AppSetting, key)
            return (
                cast(dict[str, object], dict(setting.value_payload))
                if setting is not None
                else None
            )
