"""Temporary server aliases for core-owned relational records."""

from media_finder_core.acquisition.persistence import AcquisitionRecord as Acquisition
from media_finder_core.catalog.persistence import (
    CollectionRecord as Collection,
)
from media_finder_core.catalog.persistence import (
    MediaItemRecord as MediaItem,
)
from media_finder_core.catalog.persistence import (
    MetadataRevisionRecord as MetadataRevision,
)
from media_finder_core.platform import Base

__all__ = [
    "Acquisition",
    "Base",
    "Collection",
    "MediaItem",
    "MetadataRevision",
]
