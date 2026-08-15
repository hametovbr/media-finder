"""Public compile-time module registration contracts."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

import httpx
from pydantic import BaseModel

from .protocols import DownloadClient, MetadataProvider
from .types import Attribution

HttpClientFactory = Callable[[], httpx.Client]
SecretResolver = Callable[[str], str]
MetadataBuilder = Callable[
    [Mapping[str, object], HttpClientFactory, SecretResolver], MetadataProvider
]
DownloadClientBuilder = Callable[
    [Mapping[str, object], HttpClientFactory, SecretResolver], DownloadClient
]


@dataclass(frozen=True, slots=True)
class MetadataProviderRegistration:
    key: str
    config_model: type[BaseModel]
    retention_factory: Callable[[], MetadataProvider]
    build: MetadataBuilder


@dataclass(frozen=True, slots=True)
class DownloadClientRegistration:
    key: str
    config_model: type[BaseModel]
    build: DownloadClientBuilder


@dataclass(frozen=True, slots=True)
class StaticModuleRegistry:
    """One immutable composition boundary for modules shipped in an image."""

    metadata_providers: Mapping[str, MetadataProviderRegistration]
    download_clients: Mapping[str, DownloadClientRegistration]
    static_attributions: tuple[Callable[[], Attribution], ...] = ()

    def __post_init__(self) -> None:
        for key, metadata_registration in self.metadata_providers.items():
            if key != metadata_registration.key:
                raise ValueError("metadata_registration_key_mismatch")
        for key, client_registration in self.download_clients.items():
            if key != client_registration.key:
                raise ValueError("download_client_registration_key_mismatch")
        object.__setattr__(
            self, "metadata_providers", MappingProxyType(dict(self.metadata_providers))
        )
        object.__setattr__(self, "download_clients", MappingProxyType(dict(self.download_clients)))

    def retention_providers(self) -> dict[str, MetadataProvider]:
        return {
            key: registration.retention_factory()
            for key, registration in self.metadata_providers.items()
        }
