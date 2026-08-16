"""Explicit typed resource graphs for server control-adapter tests."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from media_finder_core import ModuleRuntime
from media_finder_core.acquisition import ReleaseSelectionCache, ReleaseSelectionService
from media_finder_core.platform import EphemeralCache
from media_finder_metadata_manual import registration as manual_registration
from media_finder_sdk import (
    DownloadClient,
    DownloadClientRegistration,
    ExportWarning,
    MetadataProvider,
    MetadataProviderRegistration,
    ModuleError,
    ModuleFailureCategory,
    ModuleKind,
    ModuleManifest,
    ReleaseProviderRegistration,
    RetentionAction,
    RetentionActionKind,
    RetentionPolicy,
    RetentionSubject,
    StaticModuleRegistry,
)
from media_finder_server.control_gateway import BackendControlGateway
from sqlalchemy.orm import Session, sessionmaker


class _NoopRetention:
    def retention_for(self, created_at: datetime) -> RetentionPolicy:
        del created_at
        return RetentionPolicy()

    def plan(self, subject: RetentionSubject, now: datetime) -> RetentionAction:
        del subject, now
        return RetentionAction(kind=RetentionActionKind.NONE)

    def export_warning(self, policy: RetentionPolicy, now: datetime) -> ExportWarning | None:
        del policy, now
        return None

    def close(self) -> None:
        return None


class _UnavailableReleaseProvider:
    def validate(self) -> None:
        raise ModuleError(
            category=ModuleFailureCategory.UNAVAILABLE,
            code="release_provider_unavailable",
        )

    def search(self, query):  # type: ignore[no-untyped-def]
        del query
        return ()

    def resolve(self, selection):  # type: ignore[no-untyped-def]
        del selection
        raise AssertionError("unavailable_release_provider_resolved")

    def close(self) -> None:
        return None


class _UnavailableDownloadClient:
    def validate(self) -> None:
        raise ModuleError(
            category=ModuleFailureCategory.UNAVAILABLE,
            code="download_client_unavailable",
        )

    def list_destinations(self):  # type: ignore[no-untyped-def]
        return ()

    def submit(self, artifact, destination, correlation):  # type: ignore[no-untyped-def]
        del artifact, destination, correlation
        raise AssertionError("unavailable_download_client_submitted")

    def find_by_correlation(self, correlation):  # type: ignore[no-untyped-def]
        del correlation
        raise AssertionError("unavailable_download_client_queried")

    def close(self) -> None:
        return None


def create_gateway(
    database: Session,
    *,
    metadata_provider: MetadataProvider | None = None,
    metadata_providers: tuple[MetadataProvider, ...] = (),
    release_selections: ReleaseSelectionService | None = None,
    download_client: DownloadClient | None = None,
    release_id: str = "fixture-release",
    release_version: str = "1.2.3",
    download_id: str = "fixture-download",
    download_version: str = "9.8.7",
    release_manifest: ModuleManifest | None = None,
    download_manifest: ModuleManifest | None = None,
    environment: Mapping[str, str] | None = None,
    build_version: str = "0.1.0",
) -> BackendControlGateway:
    metadata = [manual_registration()]
    selected_metadata = (
        (*metadata_providers, metadata_provider)
        if metadata_provider is not None
        else metadata_providers
    )
    for selected_provider in selected_metadata:
        metadata.append(
            MetadataProviderRegistration(
                manifest=selected_provider.manifest,
                build=lambda _environment, provider=selected_provider: provider,
                retention=_NoopRetention,
            )
        )
    release_registration = ReleaseProviderRegistration(
        manifest=release_manifest
        or _manifest(
            release_id,
            ModuleKind.RELEASE_PROVIDER,
            release_version,
            frozenset({"search", "resolve", "magnet"}),
        ),
        build=lambda _environment: _UnavailableReleaseProvider(),
    )
    selected_client = download_client or _UnavailableDownloadClient()
    download_registration = DownloadClientRegistration(
        manifest=download_manifest
        or _manifest(
            download_id,
            ModuleKind.DOWNLOAD_CLIENT,
            download_version,
            frozenset({"destinations", "submit", "correlation", "magnet", "torrent"}),
        ),
        build=lambda _environment: selected_client,
    )
    registry = StaticModuleRegistry.create(
        metadata=tuple(metadata),
        release=(release_registration,),
        download=(download_registration,),
    )
    runtime = ModuleRuntime(registry=registry, environment=environment or {})
    selections = release_selections or ReleaseSelectionService(
        provider=lambda: runtime.release_provider(release_id),
        cache=ReleaseSelectionCache(),
    )
    sessions = sessionmaker(bind=database.get_bind(), expire_on_commit=False)
    gateway = BackendControlGateway(
        sessions=sessions,
        cursor_secret=b"cursor-secret-for-tests",
        registry=registry,
        module_runtime=runtime,
        release_selections=selections,
        release_manifest=release_registration.manifest,
        download_manifest=download_registration.manifest,
        environment=environment or {},
        attribution_notices={
            "module.manual.notice": "User-provided metadata",
            **{
                registration.manifest.attribution.notice_key: (
                    f"Fixture data from {registration.manifest.module_id}"
                )
                for registration in metadata
                if registration.manifest.attribution is not None
            },
        },
        metadata_selections=EphemeralCache(),
        manual_drafts=EphemeralCache(),
        build_version=build_version,
    )
    gateway._test_runtime = runtime  # type: ignore[attr-defined]
    gateway._test_release_selections = selections  # type: ignore[attr-defined]
    return gateway


def _manifest(
    module_id: str,
    kind: ModuleKind,
    version: str,
    capabilities: frozenset[str],
) -> ModuleManifest:
    return ModuleManifest(
        module_id=module_id,
        module_kind=kind,
        module_version=version,
        sdk_compatibility=">=1,<2",
        contract_version="1",
        capabilities=capabilities,
        name_key=f"module.{module_id}.name",
        translation_keys=frozenset({f"module.{module_id}.name"}),
    )


__all__ = ["create_gateway"]
