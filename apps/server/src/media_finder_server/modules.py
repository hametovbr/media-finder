"""The sole concrete first-party module composition boundary."""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib.resources import files
from types import MappingProxyType

import httpx
from media_finder_core import ModuleRuntime
from media_finder_core.acquisition import ReleaseSelectionCache, ReleaseSelectionService
from media_finder_download_qbittorrent import registration as qbittorrent_registration
from media_finder_metadata_manual import registration as manual_registration
from media_finder_metadata_tmdb import registration as tmdb_registration
from media_finder_release_prowlarr import registration as prowlarr_registration
from media_finder_sdk import (
    ModuleManifest,
    StaticModuleRegistry,
)

SELECTED_RELEASE_MODULE_ID = "prowlarr"
SELECTED_DOWNLOAD_MODULE_ID = "qbittorrent"


@dataclass(frozen=True, slots=True)
class RuntimeModuleComposition:
    registry: StaticModuleRegistry
    runtime: ModuleRuntime
    release_manifest: ModuleManifest
    download_manifest: ModuleManifest
    release_selections: ReleaseSelectionService
    attribution_notices: Mapping[str, str]


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


def create_runtime_module_composition(
    *,
    environment: Mapping[str, str],
    release_cache: ReleaseSelectionCache,
    client_factory: Callable[[], httpx.Client] = httpx.Client,
) -> RuntimeModuleComposition:
    """Create one typed registry and one lifecycle for the production resource graph."""

    registry = _create_module_registry(client_factory)
    runtime = ModuleRuntime(registry=registry, environment=environment)
    release_registration = registry.release[SELECTED_RELEASE_MODULE_ID]
    download_registration = registry.download[SELECTED_DOWNLOAD_MODULE_ID]

    return RuntimeModuleComposition(
        registry=registry,
        runtime=runtime,
        release_manifest=release_registration.manifest,
        download_manifest=download_registration.manifest,
        release_selections=ReleaseSelectionService(
            provider=lambda: runtime.release_provider(release_registration.manifest.module_id),
            cache=release_cache,
        ),
        attribution_notices=MappingProxyType(
            {
                **_english_translations("media_finder_metadata_manual"),
                **_english_translations("media_finder_metadata_tmdb"),
            }
        ),
    )


def _english_translations(package: str) -> dict[str, str]:
    payload = json.loads(
        files(package).joinpath("translations/en.json").read_text(encoding="utf-8")
    )
    if not isinstance(payload, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in payload.items()
    ):
        raise ValueError("module_translation_catalog_invalid")
    return payload


__all__ = [
    "RuntimeModuleComposition",
    "create_module_registry",
    "create_runtime_module_composition",
]
