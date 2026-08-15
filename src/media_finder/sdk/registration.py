"""Public compile-time module registration contracts."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

import httpx
from pydantic import BaseModel

from .protocols import DownloadClient, MetadataProvider
from .types import Attribution, EnvironmentVariableSpec

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
    environment: tuple[EnvironmentVariableSpec, ...] = ()


@dataclass(frozen=True, slots=True)
class DownloadClientRegistration:
    key: str
    config_model: type[BaseModel]
    build: DownloadClientBuilder
    environment: tuple[EnvironmentVariableSpec, ...] = ()


@dataclass(frozen=True, slots=True)
class IntegrationDescriptor:
    """Static environment contract for a core-owned external integration."""

    key: str
    environment: tuple[EnvironmentVariableSpec, ...]

    def __post_init__(self) -> None:
        _validate_environment(self.environment)


class EnvironmentConfigurationError(ValueError):
    """Safe missing-environment failure that never includes resolved values."""

    code = "integration_environment_missing"

    def __init__(self, missing: tuple[str, ...]) -> None:
        self.missing = missing
        super().__init__(f"{self.code}: {', '.join(missing)}")


def resolve_environment(
    declarations: tuple[EnvironmentVariableSpec, ...],
    environment: Mapping[str, str],
) -> dict[str, str]:
    """Resolve a declared contract without exposing values in failures."""

    _validate_environment(declarations)
    missing = tuple(
        declaration.name
        for declaration in declarations
        if declaration.required and not environment.get(declaration.name, "").strip()
    )
    if missing:
        raise EnvironmentConfigurationError(missing)
    return {
        declaration.name: environment[declaration.name]
        for declaration in declarations
        if environment.get(declaration.name, "").strip()
    }


def _validate_environment(declarations: tuple[EnvironmentVariableSpec, ...]) -> None:
    names = [declaration.name for declaration in declarations]
    if len(names) != len(set(names)):
        raise ValueError("environment_variable_duplicate")


@dataclass(frozen=True, slots=True)
class StaticModuleRegistry:
    """One immutable composition boundary for modules shipped in an image."""

    metadata_providers: Mapping[str, MetadataProviderRegistration]
    download_clients: Mapping[str, DownloadClientRegistration]
    static_attributions: tuple[Callable[[], Attribution], ...] = ()

    def __post_init__(self) -> None:
        declared: dict[str, EnvironmentVariableSpec] = {}
        for key, metadata_registration in self.metadata_providers.items():
            if key != metadata_registration.key:
                raise ValueError("metadata_registration_key_mismatch")
            _validate_environment(metadata_registration.environment)
            _merge_environment(declared, metadata_registration.environment)
        for key, client_registration in self.download_clients.items():
            if key != client_registration.key:
                raise ValueError("download_client_registration_key_mismatch")
            _validate_environment(client_registration.environment)
            _merge_environment(declared, client_registration.environment)
        object.__setattr__(
            self, "metadata_providers", MappingProxyType(dict(self.metadata_providers))
        )
        object.__setattr__(self, "download_clients", MappingProxyType(dict(self.download_clients)))

    def retention_providers(self) -> dict[str, MetadataProvider]:
        return {
            key: registration.retention_factory()
            for key, registration in self.metadata_providers.items()
        }


def _merge_environment(
    declared: dict[str, EnvironmentVariableSpec],
    additions: tuple[EnvironmentVariableSpec, ...],
) -> None:
    for addition in additions:
        existing = declared.get(addition.name)
        if existing is not None and existing != addition:
            raise ValueError("environment_variable_conflict")
        declared[addition.name] = addition
