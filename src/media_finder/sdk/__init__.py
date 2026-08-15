"""Versioned public contracts for statically packaged modules."""

from .errors import ModuleError
from .protocols import DownloadClient, MetadataProvider
from .registration import (
    DownloadClientRegistration,
    MetadataProviderRegistration,
    StaticModuleRegistry,
)
from .settings import EnvReference
from .types import ExportHeader, ExportWarning, ModuleManifest, NormalizedMetadata

__all__ = [
    "DownloadClient",
    "DownloadClientRegistration",
    "EnvReference",
    "ExportHeader",
    "ExportWarning",
    "MetadataProvider",
    "MetadataProviderRegistration",
    "ModuleError",
    "ModuleManifest",
    "NormalizedMetadata",
    "StaticModuleRegistry",
]
