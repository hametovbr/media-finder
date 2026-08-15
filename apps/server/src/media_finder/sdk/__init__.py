"""Versioned public contracts for statically packaged modules."""

from .conformance import (
    ClientConformanceFixture,
    ProviderConformanceFixture,
    assert_client_conforms,
    assert_client_registration_conforms,
    assert_environment_conforms,
    assert_provider_conforms,
    assert_provider_registration_conforms,
)
from .errors import ModuleError
from .protocols import DownloadClient, MetadataProvider
from .registration import (
    DownloadClientRegistration,
    EnvironmentConfigurationError,
    IntegrationDescriptor,
    MetadataProviderRegistration,
    StaticModuleRegistry,
    resolve_environment,
)
from .settings import EnvReference
from .types import (
    EnvironmentVariableSpec,
    ExportHeader,
    ExportWarning,
    ModuleManifest,
    NormalizedMetadata,
)

__all__ = [
    "ClientConformanceFixture",
    "DownloadClient",
    "DownloadClientRegistration",
    "EnvReference",
    "EnvironmentConfigurationError",
    "EnvironmentVariableSpec",
    "ExportHeader",
    "ExportWarning",
    "IntegrationDescriptor",
    "MetadataProvider",
    "MetadataProviderRegistration",
    "ModuleError",
    "ModuleManifest",
    "NormalizedMetadata",
    "ProviderConformanceFixture",
    "StaticModuleRegistry",
    "assert_client_conforms",
    "assert_client_registration_conforms",
    "assert_environment_conforms",
    "assert_provider_conforms",
    "assert_provider_registration_conforms",
    "resolve_environment",
]
