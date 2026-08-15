"""Versioned public contracts for statically packaged modules."""

from .errors import ModuleError
from .protocols import DownloadClient, MetadataProvider
from .types import ModuleManifest, NormalizedMetadata

__all__ = [
    "DownloadClient",
    "MetadataProvider",
    "ModuleError",
    "ModuleManifest",
    "NormalizedMetadata",
]
