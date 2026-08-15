"""Versioned public contracts for statically packaged modules."""

from .errors import ModuleError
from .protocols import DownloadClient, MetadataProvider
from .types import ExportHeader, ExportWarning, ModuleManifest, NormalizedMetadata

__all__ = [
    "DownloadClient",
    "ExportHeader",
    "ExportWarning",
    "MetadataProvider",
    "ModuleError",
    "ModuleManifest",
    "NormalizedMetadata",
]
