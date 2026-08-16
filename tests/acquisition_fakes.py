"""Typed acquisition-module fixtures shared by server and UI tests."""

from __future__ import annotations

from media_finder_core.acquisition import ModuleVersionSnapshot, ReleaseSelectionService
from media_finder_core.control import ControlPortError
from media_finder_sdk import (
    DownloadClient,
    EnvironmentVariableSpec,
    ModuleKind,
    ModuleManifest,
)


def _manifest(module_id: str, kind: ModuleKind, version: str) -> ModuleManifest:
    capabilities = (
        frozenset({"search", "resolve", "magnet"})
        if kind is ModuleKind.RELEASE_PROVIDER
        else frozenset({"destinations", "submit", "correlation", "magnet", "torrent"})
    )
    environment = (
        (
            EnvironmentVariableSpec(
                name="PROWLARR_URL",
                required=True,
                secret=False,
                description_key="module.prowlarr.environment.url",
            ),
            EnvironmentVariableSpec(
                name="PROWLARR_API_KEY",
                required=True,
                secret=True,
                description_key="module.prowlarr.environment.api-key",
            ),
        )
        if module_id == "prowlarr"
        else (
            EnvironmentVariableSpec(
                name="QBITTORRENT_URL",
                required=True,
                secret=False,
                description_key="module.qbittorrent.environment.url",
            ),
            EnvironmentVariableSpec(
                name="QBITTORRENT_USERNAME",
                required=True,
                secret=False,
                description_key="module.qbittorrent.environment.username",
            ),
            EnvironmentVariableSpec(
                name="QBITTORRENT_PASSWORD",
                required=True,
                secret=True,
                description_key="module.qbittorrent.environment.password",
            ),
        )
        if module_id == "qbittorrent"
        else ()
    )
    return ModuleManifest(
        module_id=module_id,
        module_kind=kind,
        module_version=version,
        sdk_compatibility=">=1,<2",
        contract_version="1",
        capabilities=capabilities,
        name_key=f"module.{module_id}.name",
        translation_keys=frozenset(
            {f"module.{module_id}.name"} | {value.description_key for value in environment}
        ),
        environment=environment,
    )


class StaticAcquisitionModules:
    """Expose one selected release provider and download client through the host seam."""

    def __init__(
        self,
        *,
        releases: ReleaseSelectionService | None,
        download_client: DownloadClient | None,
        release_id: str = "fixture-release",
        release_version: str = "1.2.3",
        download_id: str = "fixture-download",
        download_version: str = "9.8.7",
    ) -> None:
        self.release_manifest = _manifest(
            release_id,
            ModuleKind.RELEASE_PROVIDER,
            release_version,
        )
        self.download_manifest = _manifest(
            download_id,
            ModuleKind.DOWNLOAD_CLIENT,
            download_version,
        )
        self._releases = releases
        self._download_client = download_client

    def release_selections(self) -> ReleaseSelectionService:
        if self._releases is None:
            raise ControlPortError("release_provider_unavailable")
        return self._releases

    def download_client(self) -> DownloadClient:
        if self._download_client is None:
            raise ControlPortError("download_client_unavailable")
        return self._download_client

    def release_module(self) -> ModuleVersionSnapshot:
        return ModuleVersionSnapshot(
            module_id=self.release_manifest.module_id,
            module_version=self.release_manifest.module_version,
        )

    def download_module(self) -> ModuleVersionSnapshot:
        return ModuleVersionSnapshot(
            module_id=self.download_manifest.module_id,
            module_version=self.download_manifest.module_version,
        )


__all__ = ["StaticAcquisitionModules"]
