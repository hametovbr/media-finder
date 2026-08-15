"""The sole concrete first-party module composition boundary."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

import httpx
from media_finder.modules.registry import create_legacy_registry
from media_finder.sdk.registration import StaticModuleRegistry as LegacyModuleRegistry
from media_finder_core import ModuleRuntime
from media_finder_download_qbittorrent import registration as qbittorrent_registration
from media_finder_metadata_manual import registration as manual_registration
from media_finder_metadata_tmdb import registration as tmdb_registration
from media_finder_release_prowlarr import registration as prowlarr_registration
from media_finder_sdk import (
    DownloadArtifact,
    DownloadClientRegistration,
    MetadataProviderRegistration,
    PrivateReleaseSelection,
    ReleaseCandidate,
    ReleaseProviderRegistration,
    ReleaseSearchQuery,
    StaticModuleRegistry,
)


@dataclass(frozen=True, slots=True)
class RuntimeModuleComposition:
    registry: StaticModuleRegistry
    runtime: ModuleRuntime
    legacy_registry: LegacyModuleRegistry
    release_registration_factory: Callable[
        [Callable[[], httpx.Client]], ReleaseProviderRegistration
    ]


class _BorrowedReleaseProvider:
    """Legacy bridge whose concrete capability remains owned by ModuleRuntime."""

    def __init__(self, runtime: ModuleRuntime, module_id: str) -> None:
        self._provider = runtime.release_provider(module_id)

    def validate(self) -> None:
        return None

    def search(self, query: ReleaseSearchQuery) -> tuple[ReleaseCandidate, ...]:
        return self._provider.search(query)

    def resolve(self, selection: PrivateReleaseSelection) -> DownloadArtifact:
        return self._provider.resolve(selection)

    def close(self) -> None:
        return None


def create_module_registry() -> StaticModuleRegistry:
    """Return a fresh immutable registry for the modules shipped in the image."""

    return _create_module_registry(httpx.Client)


def _create_module_registry(
    client_factory: Callable[[], httpx.Client],
) -> StaticModuleRegistry:
    return StaticModuleRegistry.create(
        metadata=(manual_registration(), tmdb_registration(client_factory=client_factory)),
        release=(prowlarr_registration(client_factory=client_factory),),
        download=(qbittorrent_registration(client_factory=client_factory),),
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


def create_release_registration(
    client_factory: Callable[[], httpx.Client] = httpx.Client,
) -> ReleaseProviderRegistration:
    """Build the selected first-party release registration."""

    return prowlarr_registration(client_factory=client_factory)


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
    release_registration = registry.release["prowlarr"]

    def borrowed_release_registration(
        ignored_client_factory: Callable[[], httpx.Client],
    ) -> ReleaseProviderRegistration:
        del ignored_client_factory
        return ReleaseProviderRegistration(
            manifest=release_registration.manifest,
            build=lambda ignored_environment: _BorrowedReleaseProvider(
                runtime,
                release_registration.manifest.module_id,
            ),
        )

    return RuntimeModuleComposition(
        registry=registry,
        runtime=runtime,
        legacy_registry=legacy_registry,
        release_registration_factory=borrowed_release_registration,
    )


__all__ = [
    "RuntimeModuleComposition",
    "create_legacy_module_registry",
    "create_module_registry",
    "create_release_registration",
    "create_runtime_module_composition",
]
