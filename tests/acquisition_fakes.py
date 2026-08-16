"""Typed acquisition-module fixtures shared by server and UI tests."""

from __future__ import annotations

from media_finder_core.acquisition import ReleaseSelectionService
from media_finder_sdk import (
    CorrelationResult,
    DownloadArtifact,
    DownloadClient,
    DownloadDestination,
    EnvironmentVariableSpec,
    ModuleKind,
    ModuleManifest,
    SubmissionResult,
)
from media_finder_server.integration_runtime import RuntimeResult


def _manifest(module_id: str, kind: ModuleKind, version: str) -> ModuleManifest:
    capabilities = (
        frozenset({"search", "resolve"})
        if kind is ModuleKind.RELEASE_PROVIDER
        else frozenset({"magnet", "torrent"})
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
        self._download_client = (
            _TypedDownloadClient(download_client) if download_client is not None else None
        )

    def release_selections(self) -> RuntimeResult[ReleaseSelectionService]:
        return RuntimeResult(
            self._releases,
            None if self._releases is not None else "release_provider_unavailable",
        )

    def selected_download_client(self) -> RuntimeResult[DownloadClient]:
        return RuntimeResult(
            self._download_client,
            None if self._download_client is not None else "download_client_unavailable",
        )


__all__ = ["StaticAcquisitionModules"]


class _TypedDownloadClient:
    """Adapt transitional server test doubles to the canonical SDK protocol."""

    def __init__(self, client: object) -> None:
        self._client = client

    def validate(self) -> None:
        validate = getattr(self._client, "validate", None)
        if callable(validate):
            validate()
            return
        validate_config = self._client.validate_config
        validate_config()

    def list_destinations(self) -> tuple[DownloadDestination, ...]:
        values = self._client.list_destinations()
        return tuple(
            DownloadDestination.model_validate(value.model_dump(mode="json")) for value in values
        )

    def submit(
        self,
        artifact: DownloadArtifact,
        destination: str,
        correlation: str,
    ) -> SubmissionResult:
        value = self._client.submit(artifact, destination, correlation)
        return SubmissionResult.model_validate(value.model_dump(mode="json"))

    def find_by_correlation(self, correlation: str) -> CorrelationResult:
        value = self._client.find_by_correlation(correlation)
        return CorrelationResult.model_validate(value.model_dump(mode="json"))

    def close(self) -> None:
        return None
