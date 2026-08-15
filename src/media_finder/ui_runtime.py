"""Persisted-settings runtime construction boundary for the browser UI."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator
from sqlalchemy.orm import Session, sessionmaker

from .acquisition import ClientLoader
from .config import EnvReference
from .models import AppSetting, DownloadClientInstance
from .prowlarr import ProwlarrAdapter
from .sdk.protocols import DownloadClient, MetadataProvider


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
        if value.username or value.password or value.query or value.fragment:
            raise ValueError("prowlarr_base_url_invalid")
        return value

    @field_validator("api_key_ref")
    @classmethod
    def environment_reference(cls, value: str) -> str:
        return EnvReference(value=value).value


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
            return RuntimeResult(None, "metadata_provider_not_configured")
        try:
            result = self._factory.metadata_provider(key, payload)
            if result.value is not None:
                result.value.validate_config()
            return result
        except Exception:
            return RuntimeResult(None, "metadata_provider_configuration_invalid")

    def metadata_providers(self) -> dict[str, MetadataProvider]:
        configured: dict[str, MetadataProvider] = {}
        for key in self._providers:
            result = self.metadata_provider(key)
            if result.value is not None:
                configured[key] = result.value
        return configured

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
                if result.value is not None:
                    result.value.validate_config()
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
