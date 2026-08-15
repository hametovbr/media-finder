"""Public module contracts for Media Finder extensions."""

from .common import PublicModel
from .environment import ResolvedModuleEnvironment, resolve_module_environment
from .errors import JsonScalar, JsonValue, ModuleError, ModuleFailureCategory
from .manifest import (
    AttributionSpec,
    EnvironmentVariableSpec,
    ModuleKind,
    ModuleManifest,
    load_manifest,
    parse_manifest,
)
from .registration import (
    SDK_VERSION,
    SUPPORTED_CONTRACT_VERSION,
    CloseableModule,
    DownloadClientRegistration,
    MetadataProviderRegistration,
    ReleaseProviderRegistration,
    StaticModuleRegistry,
)

__all__ = [
    "SDK_VERSION",
    "SUPPORTED_CONTRACT_VERSION",
    "AttributionSpec",
    "CloseableModule",
    "DownloadClientRegistration",
    "EnvironmentVariableSpec",
    "JsonScalar",
    "JsonValue",
    "MetadataProviderRegistration",
    "ModuleError",
    "ModuleFailureCategory",
    "ModuleKind",
    "ModuleManifest",
    "PublicModel",
    "ReleaseProviderRegistration",
    "ResolvedModuleEnvironment",
    "StaticModuleRegistry",
    "load_manifest",
    "parse_manifest",
    "resolve_module_environment",
]
