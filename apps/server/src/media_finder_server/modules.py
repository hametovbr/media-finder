"""The sole concrete first-party module composition boundary."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

import httpx
from media_finder.modules.registry import create_legacy_registry
from media_finder.sdk.registration import StaticModuleRegistry as LegacyModuleRegistry
from media_finder_core import ModuleRuntime
from media_finder_core.acquisition import ReleaseSelectionCache, ReleaseSelectionService
from media_finder_download_qbittorrent import registration as qbittorrent_registration
from media_finder_metadata_manual import registration as manual_registration
from media_finder_metadata_tmdb import registration as tmdb_registration
from media_finder_release_prowlarr import registration as prowlarr_registration
from media_finder_sdk import (
    DownloadClientRegistration,
    MetadataProviderRegistration,
    ModuleManifest,
    StaticModuleRegistry,
)

SELECTED_RELEASE_MODULE_ID = "prowlarr"
SELECTED_DOWNLOAD_MODULE_ID = "qbittorrent"


@dataclass(frozen=True, slots=True)
class RuntimeModuleComposition:
    registry: StaticModuleRegistry
    runtime: ModuleRuntime
    legacy_registry: LegacyModuleRegistry
    release_manifest: ModuleManifest
    download_manifest: ModuleManifest
    release_selections: ReleaseSelectionService


def create_module_registry() -> StaticModuleRegistry:
    """Return a fresh immutable registry for the modules shipped in the image."""

    return _create_module_registry(httpx.Client)


def _create_module_registry(
    client_factory: Callable[[], httpx.Client],
) -> StaticModuleRegistry:
    manual = manual_registration()
    tmdb = tmdb_registration(client_factory=client_factory)
    release = prowlarr_registration(client_factory=client_factory)
    download = qbittorrent_registration(client_factory=client_factory)
    return StaticModuleRegistry.create(
        metadata=(manual, tmdb),
        release=(release,),
        download=(download,),
    )


def create_legacy_module_registry() -> LegacyModuleRegistry:
    """Bridge the new host registry while legacy contexts are moved into core."""

    registry = create_module_registry()
    return create_legacy_registry(
        editor_metadata=registry.metadata["manual"],
        remote_metadata=registry.metadata["tmdb"],
        remote_metadata_factory=_tmdb_registration,
        download=registry.download["qbittorrent"],
        download_factory=_qbittorrent_registration,
    )


def _tmdb_registration(
    client_factory: Callable[[], httpx.Client],
) -> MetadataProviderRegistration:
    return tmdb_registration(client_factory=client_factory)


def _qbittorrent_registration(
    client_factory: Callable[[], httpx.Client],
) -> DownloadClientRegistration:
    return qbittorrent_registration(client_factory=client_factory)


def create_runtime_module_composition(
    *,
    environment: Mapping[str, str],
    client_factory: Callable[[], httpx.Client] = httpx.Client,
) -> RuntimeModuleComposition:
    """Create one typed registry and one lifecycle for the production resource graph."""

    registry = _create_module_registry(client_factory)
    runtime = ModuleRuntime(registry=registry, environment=environment)
    legacy_registry = create_legacy_registry(
        editor_metadata=registry.metadata["manual"],
        remote_metadata=registry.metadata["tmdb"],
        remote_metadata_factory=_tmdb_registration,
        download=registry.download["qbittorrent"],
        download_factory=_qbittorrent_registration,
        runtime=runtime,
    )
    release_registration = registry.release[SELECTED_RELEASE_MODULE_ID]
    download_registration = registry.download[SELECTED_DOWNLOAD_MODULE_ID]

    return RuntimeModuleComposition(
        registry=registry,
        runtime=runtime,
        legacy_registry=legacy_registry,
        release_manifest=release_registration.manifest,
        download_manifest=download_registration.manifest,
        release_selections=ReleaseSelectionService(
            provider=lambda: runtime.release_provider(release_registration.manifest.module_id),
            cache=ReleaseSelectionCache(),
        ),
    )


__all__ = [
    "RuntimeModuleComposition",
    "create_legacy_module_registry",
    "create_module_registry",
    "create_runtime_module_composition",
]
