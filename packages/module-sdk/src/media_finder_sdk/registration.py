"""Typed static module registrations and registry validation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol

from packaging.version import Version

from .environment import ResolvedModuleEnvironment
from .manifest import EnvironmentVariableSpec, ModuleKind, ModuleManifest

SDK_VERSION = Version("1.0.0")
SUPPORTED_CONTRACT_VERSION = "1"


class CloseableModule(Protocol):
    """Minimum lifecycle surface returned by a module factory."""

    def close(self) -> None: ...


type ModuleFactory = Callable[[ResolvedModuleEnvironment], CloseableModule]
type RetentionFactory = Callable[[], CloseableModule]


@dataclass(frozen=True, slots=True)
class MetadataProviderRegistration:
    manifest: ModuleManifest
    build: ModuleFactory
    retention: RetentionFactory


@dataclass(frozen=True, slots=True)
class ReleaseProviderRegistration:
    manifest: ModuleManifest
    build: ModuleFactory


@dataclass(frozen=True, slots=True)
class DownloadClientRegistration:
    manifest: ModuleManifest
    build: ModuleFactory


type MetadataRegistrationMap = Mapping[str, MetadataProviderRegistration]
type ReleaseRegistrationMap = Mapping[str, ReleaseProviderRegistration]
type DownloadRegistrationMap = Mapping[str, DownloadClientRegistration]


@dataclass(frozen=True, slots=True)
class StaticModuleRegistry:
    """One immutable, capability-separated composition boundary."""

    metadata: MetadataRegistrationMap
    release: ReleaseRegistrationMap
    download: DownloadRegistrationMap

    @classmethod
    def create(
        cls,
        *,
        metadata: tuple[MetadataProviderRegistration, ...] = (),
        release: tuple[ReleaseProviderRegistration, ...] = (),
        download: tuple[DownloadClientRegistration, ...] = (),
    ) -> StaticModuleRegistry:
        declared_ids: set[str] = set()
        declared_environment: dict[str, EnvironmentVariableSpec] = {}
        typed_registrations: tuple[
            tuple[
                ModuleKind,
                tuple[
                    MetadataProviderRegistration
                    | ReleaseProviderRegistration
                    | DownloadClientRegistration,
                    ...,
                ],
            ],
            ...,
        ] = (
            (ModuleKind.METADATA_PROVIDER, metadata),
            (ModuleKind.RELEASE_PROVIDER, release),
            (ModuleKind.DOWNLOAD_CLIENT, download),
        )
        for expected_kind, registrations in typed_registrations:
            for registration in registrations:
                manifest = registration.manifest
                if manifest.module_id in declared_ids:
                    raise ValueError("module_identity_duplicate")
                declared_ids.add(manifest.module_id)
                _validate_manifest(manifest, expected_kind)
                _merge_environment(declared_environment, manifest.environment)

        return cls(
            metadata=MappingProxyType(
                {registration.manifest.module_id: registration for registration in metadata}
            ),
            release=MappingProxyType(
                {registration.manifest.module_id: registration for registration in release}
            ),
            download=MappingProxyType(
                {registration.manifest.module_id: registration for registration in download}
            ),
        )


_CAPABILITIES = {
    ModuleKind.METADATA_PROVIDER: (
        frozenset({"search", "fetch", "normalize"}),
        frozenset({"search", "fetch", "normalize", "retention", "export-warning"}),
    ),
    ModuleKind.RELEASE_PROVIDER: (
        frozenset({"search", "resolve"}),
        frozenset({"search", "resolve", "magnet", "torrent"}),
    ),
    ModuleKind.DOWNLOAD_CLIENT: (
        frozenset({"destinations", "submit", "correlation"}),
        frozenset({"destinations", "submit", "correlation", "magnet", "torrent"}),
    ),
}


def _validate_manifest(manifest: ModuleManifest, expected_kind: ModuleKind) -> None:
    if manifest.module_kind is not expected_kind:
        raise ValueError("module_registration_kind_mismatch")
    if SDK_VERSION not in manifest.sdk_range():
        raise ValueError("module_sdk_incompatible")
    if manifest.contract_version != SUPPORTED_CONTRACT_VERSION:
        raise ValueError("module_contract_unsupported")
    required, allowed = _CAPABILITIES[expected_kind]
    capabilities = manifest.capabilities
    if not required.issubset(capabilities) or not capabilities.issubset(allowed):
        raise ValueError("module_capability_invalid")
    if expected_kind in {ModuleKind.RELEASE_PROVIDER, ModuleKind.DOWNLOAD_CLIENT} and not (
        capabilities & {"magnet", "torrent"}
    ):
        raise ValueError("module_capability_invalid")


def _merge_environment(
    declared: dict[str, EnvironmentVariableSpec],
    additions: tuple[EnvironmentVariableSpec, ...],
) -> None:
    for addition in additions:
        existing = declared.get(addition.name)
        if existing is not None and existing != addition:
            raise ValueError("module_environment_conflict")
        declared[addition.name] = addition


__all__ = [
    "SDK_VERSION",
    "SUPPORTED_CONTRACT_VERSION",
    "CloseableModule",
    "DownloadClientRegistration",
    "MetadataProviderRegistration",
    "ReleaseProviderRegistration",
    "StaticModuleRegistry",
]
