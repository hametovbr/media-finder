"""Typed access to the host-supplied immutable module registry."""

from __future__ import annotations

from media_finder_sdk import (
    DownloadClientRegistration,
    MetadataProviderRegistration,
    ReleaseProviderRegistration,
    StaticModuleRegistry,
)

from .diagnostics import _module_not_found


class _RegistryAccess:
    """Resolve registrations without introducing module-specific branches."""

    def __init__(self, registry: StaticModuleRegistry) -> None:
        self._registry = registry

    @property
    def registry(self) -> StaticModuleRegistry:
        return self._registry

    def metadata(self, module_id: str) -> MetadataProviderRegistration:
        registration = self._registry.metadata.get(module_id)
        if registration is None:
            raise _module_not_found()
        return registration

    def release(self, module_id: str) -> ReleaseProviderRegistration:
        registration = self._registry.release.get(module_id)
        if registration is None:
            raise _module_not_found()
        return registration

    def download(self, module_id: str) -> DownloadClientRegistration:
        registration = self._registry.download.get(module_id)
        if registration is None:
            raise _module_not_found()
        return registration


__all__: list[str] = []
