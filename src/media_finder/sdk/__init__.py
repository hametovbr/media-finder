"""Versioned public contracts for statically packaged modules."""

from .errors import ModuleError
from .protocols import DownloadClient, MetadataProvider
from .types import ExportWarning, ModuleManifest, NormalizedMetadata

__all__ = [
    "DownloadClient",
    "ExportWarning",
    "MetadataProvider",
    "ModuleError",
    "ModuleManifest",
    "NormalizedMetadata",
]
