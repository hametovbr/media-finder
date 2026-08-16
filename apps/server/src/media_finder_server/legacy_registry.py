"""The single compile-time composition boundary for first-party modules."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Protocol, cast

from media_finder_sdk import (
    CorrelationResult as SDKCorrelationResult,
)
from media_finder_sdk import (
    DownloadClient as SDKDownloadClient,
)
from media_finder_sdk import DownloadClientRegistration as SDKDownloadClientRegistration
from media_finder_sdk import (
    DownloadDestination as SDKDownloadDestination,
)
from media_finder_sdk import (
    EpisodeTableDocument,
    MetadataEditResult,
    MetadataIdentity,
    MetadataImportDocument,
    MetadataSearchQuery,
    ProviderPayload,
    resolve_module_environment,
)
from media_finder_sdk import (
    MagnetArtifact as SDKMagnetArtifact,
)
from media_finder_sdk import (
    MediaKind as SDKMediaKind,
)
from media_finder_sdk import MetadataEditor as SDKMetadataEditor
from media_finder_sdk import MetadataProvider as SDKMetadataProvider
from media_finder_sdk import MetadataProviderRegistration as SDKMetadataProviderRegistration
from media_finder_sdk import MetadataRetentionPolicy as SDKMetadataRetentionPolicy
from media_finder_sdk import ModuleError as SDKModuleError
from media_finder_sdk import ModuleManifest as SDKModuleManifest
from media_finder_sdk import (
    NormalizedMetadata as SDKNormalizedMetadata,
)
from media_finder_sdk import (
    RetentionPolicy as SDKRetentionPolicy,
)
from media_finder_sdk import (
    RetentionSubject as SDKRetentionSubject,
)
from media_finder_sdk import (
    SubmissionResult as SDKSubmissionResult,
)
from media_finder_sdk import (
    TorrentArtifact as SDKTorrentArtifact,
)
from pydantic import BaseModel, ConfigDict, HttpUrl

from .legacy_sdk.errors import ModuleError
from .legacy_sdk.protocols import DownloadClient, MetadataProvider
from .legacy_sdk.registration import (
    DownloadClientRegistration,
    HttpClientFactory,
    MetadataProviderRegistration,
    SecretResolver,
    StaticModuleRegistry,
)
from .legacy_sdk.types import (
    Attribution,
    CorrelationResult,
    DownloadArtifact,
    DownloadDestination,
    EnvironmentVariableSpec,
    ExportWarning,
    MagnetArtifact,
    MediaKind,
    MetadataSearchResult,
    ModuleManifest,
    NormalizedMetadata,
    RetentionAction,
    RetentionActionKind,
    RetentionPolicy,
    SubmissionResult,
    TorrentArtifact,
)


class ManualConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _legacy_manifest(manifest: SDKModuleManifest) -> ModuleManifest:
    return ModuleManifest(
        key=manifest.module_id,
        version=manifest.module_version,
        contract_version="1",
        name_key=manifest.name_key,
        capabilities=manifest.capabilities,
        translation_keys={key: key for key in manifest.translation_keys},
    )


def _to_legacy_metadata(metadata: SDKNormalizedMetadata) -> NormalizedMetadata:
    payload = metadata.model_dump(mode="json")
    provenance = payload["provenance"]
    if not isinstance(provenance, dict):
        raise ValueError("manual_provenance_invalid")
    provenance["provider_key"] = provenance.pop("provider_id")
    return NormalizedMetadata.model_validate(payload)


def _to_sdk_metadata(metadata: NormalizedMetadata) -> SDKNormalizedMetadata:
    payload = metadata.model_dump(mode="json")
    provenance = payload["provenance"]
    if not isinstance(provenance, dict):
        raise ValueError("manual_provenance_invalid")
    provenance["provider_id"] = provenance.pop("provider_key")
    return SDKNormalizedMetadata.model_validate(payload)


class _LegacyManualAdapter:
    config_model = ManualConfig

    def __init__(
        self,
        registered: SDKMetadataProviderRegistration,
        *,
        provider: SDKMetadataProvider | None = None,
        editor: SDKMetadataEditor | None = None,
        retention: SDKMetadataRetentionPolicy | None = None,
        owns_capabilities: bool = True,
    ) -> None:
        self.manifest = _legacy_manifest(registered.manifest)
        environment = resolve_module_environment(registered.manifest, {})
        if registered.editor is None:
            raise ValueError("manual_editor_missing")
        self._provider = provider or registered.build(environment)
        self._retention = retention or registered.retention()
        self._editor = editor or registered.editor(environment)
        self._owns_capabilities = owns_capabilities

    def validate_config(self) -> None:
        if self._owns_capabilities:
            self._provider.validate()

    def search(self, query: str, locale: str) -> list[MetadataSearchResult]:
        results = self._provider.search(MetadataSearchQuery(query=query, locale=locale))
        return [
            MetadataSearchResult(
                provider_key=result.provider_id,
                external_id=result.external_id,
                kind=MediaKind(result.media_kind.value),
                title=result.title,
                year=result.year,
                locale=result.locale,
            )
            for result in results
        ]

    def fetch(self, kind: str, external_id: str, locale: str) -> dict[str, object]:
        payload = self._provider.fetch(
            MetadataIdentity(
                provider_id=self.manifest.key,
                external_id=external_id,
                media_kind=SDKMediaKind(kind),
                locale=locale,
            )
        )
        return cast(dict[str, object], payload.model_dump(mode="json")["data"])

    def normalize(
        self,
        payload: dict[str, object],
        kind: str,
        external_id: str,
        locale: str,
    ) -> NormalizedMetadata:
        normalized = self._provider.normalize(
            ProviderPayload.model_validate({"data": payload}),
            MetadataIdentity(
                provider_id=self.manifest.key,
                external_id=external_id,
                media_kind=SDKMediaKind(kind),
                locale=locale,
            ),
        )
        return _to_legacy_metadata(normalized)

    def import_document(self, document: MetadataImportDocument) -> MetadataEditResult:
        return self._editor.import_document(document)

    def merge_episode_table(
        self,
        current: SDKNormalizedMetadata,
        document: EpisodeTableDocument,
    ) -> MetadataEditResult:
        return self._editor.merge_episode_table(current, document)

    def attribution(self) -> Attribution:
        return Attribution(provider_key=self.manifest.key, notice="User-provided metadata")

    def retention_for(self, created_at: datetime) -> RetentionPolicy:
        policy = self._retention.retention_for(created_at)
        return RetentionPolicy.model_validate(policy.model_dump(mode="json"))

    def plan_retention(self, policy: RetentionPolicy, now: datetime) -> RetentionAction:
        del policy, now
        return RetentionAction(kind=RetentionActionKind.NONE)

    def export_warning(self, policy: RetentionPolicy, now: datetime) -> None:
        del policy, now
        return None

    def close(self) -> None:
        if self._owns_capabilities:
            self._editor.close()
            self._provider.close()
            self._retention.close()


class TmdbConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _LegacyTmdbAdapter:
    config_model = TmdbConfig

    def __init__(
        self,
        registered: SDKMetadataProviderRegistration,
        provider: SDKMetadataProvider | None,
        retention: SDKMetadataRetentionPolicy,
        *,
        owns_capabilities: bool = True,
    ) -> None:
        self.manifest = _legacy_manifest(registered.manifest)
        self._registered = registered
        self._provider = provider
        self._retention = retention
        self._owns_capabilities = owns_capabilities

    @classmethod
    def retention_only(cls, registered: SDKMetadataProviderRegistration) -> _LegacyTmdbAdapter:
        return cls(registered, None, registered.retention())

    def validate_config(self) -> None:
        if self._owns_capabilities:
            self._require_provider().validate()

    def search(self, query: str, locale: str) -> list[MetadataSearchResult]:
        results = self._require_provider().search(MetadataSearchQuery(query=query, locale=locale))
        return [
            MetadataSearchResult(
                provider_key=result.provider_id,
                external_id=result.external_id,
                kind=MediaKind(result.media_kind.value),
                title=result.title,
                year=result.year,
                locale=result.locale,
            )
            for result in results
        ]

    def fetch(self, kind: str, external_id: str, locale: str) -> dict[str, object]:
        payload = self._require_provider().fetch(self._identity(kind, external_id, locale))
        return cast(dict[str, object], payload.model_dump(mode="json")["data"])

    def normalize(
        self,
        payload: dict[str, object],
        kind: str,
        external_id: str,
        locale: str,
    ) -> NormalizedMetadata:
        metadata = self._require_provider().normalize(
            ProviderPayload.model_validate({"data": payload}),
            self._identity(kind, external_id, locale),
        )
        return _to_legacy_metadata(metadata)

    def attribution(self) -> Attribution:
        return Attribution(
            provider_key=self.manifest.key,
            notice="This product uses the TMDB API but is not endorsed or certified by TMDB.",
            url=HttpUrl("https://www.themoviedb.org/"),
        )

    def retention_for(self, created_at: datetime) -> RetentionPolicy:
        policy = self._retention.retention_for(created_at)
        return RetentionPolicy.model_validate(policy.model_dump(mode="json"))

    def plan_retention(self, policy: RetentionPolicy, now: datetime) -> RetentionAction:
        sdk_policy = _to_sdk_retention(policy)
        action = self._retention.plan(
            _retention_subject(self.manifest.key, sdk_policy),
            now,
        )
        return RetentionAction.model_validate(action.model_dump(mode="json"))

    def export_warning(self, policy: RetentionPolicy, now: datetime) -> ExportWarning | None:
        warning = self._retention.export_warning(_to_sdk_retention(policy), now)
        if warning is None:
            return None
        return ExportWarning.model_validate(warning.model_dump(mode="json"))

    def close(self) -> None:
        if self._owns_capabilities:
            if self._provider is not None:
                self._provider.close()
            self._retention.close()

    def _require_provider(self) -> SDKMetadataProvider:
        if self._provider is None:
            raise ModuleError(
                code="metadata_provider_not_configured",
                message="The metadata provider is not configured.",
            )
        return self._provider

    def _identity(self, kind: str, external_id: str, locale: str) -> MetadataIdentity:
        return MetadataIdentity(
            provider_id=self.manifest.key,
            external_id=external_id,
            media_kind=SDKMediaKind(kind),
            locale=locale,
        )


def _to_sdk_retention(policy: RetentionPolicy) -> SDKRetentionPolicy:
    return SDKRetentionPolicy.model_validate(policy.model_dump(mode="json"))


def _retention_subject(provider_id: str, policy: SDKRetentionPolicy) -> SDKRetentionSubject:
    return SDKRetentionSubject(
        identity=MetadataIdentity(
            provider_id=provider_id,
            external_id="0",
            media_kind=SDKMediaKind.MOVIE,
            locale="en",
        ),
        policy=policy,
    )


class QbittorrentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _LegacyQbittorrentAdapter:
    config_model = QbittorrentConfig

    def __init__(
        self,
        registered: SDKDownloadClientRegistration,
        client: SDKDownloadClient,
        *,
        owns_capability: bool = True,
    ) -> None:
        self.manifest = _legacy_manifest(registered.manifest)
        self._client = client
        self._owns_capability = owns_capability

    def validate_config(self) -> None:
        if self._owns_capability:
            self._translate(self._client.validate)

    def list_destinations(self) -> list[DownloadDestination]:
        destinations = self._translate(self._client.list_destinations)
        return [
            DownloadDestination.model_validate(item.model_dump(mode="json"))
            for item in cast(tuple[SDKDownloadDestination, ...], destinations)
        ]

    def submit(
        self,
        artifact: DownloadArtifact,
        destination: str,
        correlation: str,
    ) -> SubmissionResult:
        sdk_artifact: SDKMagnetArtifact | SDKTorrentArtifact
        if isinstance(artifact, MagnetArtifact):
            sdk_artifact = SDKMagnetArtifact(uri=artifact.uri)
        elif isinstance(artifact, TorrentArtifact):
            sdk_artifact = SDKTorrentArtifact.from_bytes(artifact.content)
        else:  # pragma: no cover - legacy union is closed
            raise ModuleError("download_artifact_unsupported", "download_artifact_unsupported")
        result = cast(
            SDKSubmissionResult,
            self._translate(lambda: self._client.submit(sdk_artifact, destination, correlation)),
        )
        return SubmissionResult.model_validate(result.model_dump(mode="json"))

    def find_by_correlation(self, correlation: str) -> CorrelationResult:
        result = cast(
            SDKCorrelationResult,
            self._translate(lambda: self._client.find_by_correlation(correlation)),
        )
        return CorrelationResult.model_validate(result.model_dump(mode="json"))

    def close(self) -> None:
        if self._owns_capability:
            self._client.close()

    @staticmethod
    def _translate(operation: Callable[[], object]) -> object:
        try:
            return operation()
        except SDKModuleError as error:
            raise ModuleError(error.code, error.code) from None


type MetadataRegistrationFactory = Callable[[HttpClientFactory], SDKMetadataProviderRegistration]
type DownloadRegistrationFactory = Callable[[HttpClientFactory], SDKDownloadClientRegistration]


class CapabilityRuntime(Protocol):
    def metadata_provider(self, module_id: str) -> SDKMetadataProvider: ...

    def metadata_editor(self, module_id: str) -> SDKMetadataEditor: ...

    def retention_policy(self, module_id: str) -> SDKMetadataRetentionPolicy: ...

    def download_client(self, module_id: str) -> SDKDownloadClient: ...


def create_legacy_registry(
    *,
    editor_metadata: SDKMetadataProviderRegistration,
    remote_metadata: SDKMetadataProviderRegistration,
    remote_metadata_factory: MetadataRegistrationFactory,
    download: SDKDownloadClientRegistration,
    download_factory: DownloadRegistrationFactory,
    runtime: CapabilityRuntime | None = None,
) -> StaticModuleRegistry:
    """Adapt the public SDK into the legacy core during bounded-context migration."""

    def build_editor(
        payload: Mapping[str, object],
        http_client: HttpClientFactory,
        secret_resolver: SecretResolver,
    ) -> MetadataProvider:
        del http_client, secret_resolver
        ManualConfig.model_validate(payload)
        if runtime is not None:
            module_id = editor_metadata.manifest.module_id
            return cast(
                MetadataProvider,
                _LegacyManualAdapter(
                    editor_metadata,
                    provider=runtime.metadata_provider(module_id),
                    editor=runtime.metadata_editor(module_id),
                    retention=runtime.retention_policy(module_id),
                    owns_capabilities=False,
                ),
            )
        return cast(MetadataProvider, _LegacyManualAdapter(editor_metadata))

    def build_remote(
        payload: Mapping[str, object],
        http_client: HttpClientFactory,
        secret_resolver: SecretResolver,
    ) -> MetadataProvider:
        del secret_resolver
        if runtime is not None:
            module_id = remote_metadata.manifest.module_id
            return cast(
                MetadataProvider,
                _LegacyTmdbAdapter(
                    remote_metadata,
                    runtime.metadata_provider(module_id),
                    runtime.retention_policy(module_id),
                    owns_capabilities=False,
                ),
            )
        registered = remote_metadata_factory(http_client)
        environment = resolve_module_environment(
            registered.manifest,
            {name: str(value) for name, value in payload.items()},
        )
        return cast(
            MetadataProvider,
            _LegacyTmdbAdapter(
                registered,
                registered.build(environment),
                registered.retention(),
            ),
        )

    def build_download(
        payload: Mapping[str, object],
        http_client: HttpClientFactory,
        secret_resolver: SecretResolver,
    ) -> DownloadClient:
        del secret_resolver
        if runtime is not None:
            module_id = download.manifest.module_id
            return cast(
                DownloadClient,
                _LegacyQbittorrentAdapter(
                    download,
                    runtime.download_client(module_id),
                    owns_capability=False,
                ),
            )
        registered = download_factory(http_client)
        environment = resolve_module_environment(
            registered.manifest,
            {name: str(value) for name, value in payload.items()},
        )
        return cast(
            DownloadClient,
            _LegacyQbittorrentAdapter(registered, registered.build(environment)),
        )

    editor_key = editor_metadata.manifest.module_id
    remote_key = remote_metadata.manifest.module_id
    download_key = download.manifest.module_id
    return StaticModuleRegistry(
        metadata_providers={
            editor_key: MetadataProviderRegistration(
                key=editor_key,
                config_model=ManualConfig,
                retention_factory=lambda: cast(
                    MetadataProvider,
                    _LegacyManualAdapter(
                        editor_metadata,
                        provider=(
                            runtime.metadata_provider(editor_key) if runtime is not None else None
                        ),
                        editor=(
                            runtime.metadata_editor(editor_key) if runtime is not None else None
                        ),
                        retention=(
                            runtime.retention_policy(editor_key) if runtime is not None else None
                        ),
                        owns_capabilities=runtime is None,
                    ),
                ),
                build=build_editor,
                environment=_legacy_environment(editor_metadata.manifest),
            ),
            remote_key: MetadataProviderRegistration(
                key=remote_key,
                config_model=TmdbConfig,
                retention_factory=lambda: cast(
                    MetadataProvider,
                    (
                        _LegacyTmdbAdapter(
                            remote_metadata,
                            None,
                            runtime.retention_policy(remote_key),
                            owns_capabilities=False,
                        )
                        if runtime is not None
                        else _LegacyTmdbAdapter.retention_only(remote_metadata)
                    ),
                ),
                build=build_remote,
                environment=_legacy_environment(remote_metadata.manifest),
            ),
        },
        download_clients={
            download_key: DownloadClientRegistration(
                key=download_key,
                config_model=QbittorrentConfig,
                build=build_download,
                environment=_legacy_environment(download.manifest),
            )
        },
    )


def _legacy_environment(
    manifest: SDKModuleManifest,
) -> tuple[EnvironmentVariableSpec, ...]:
    return tuple(
        EnvironmentVariableSpec.model_validate(item.model_dump(mode="json"))
        for item in manifest.environment
    )


__all__ = [
    "DownloadRegistrationFactory",
    "MetadataRegistrationFactory",
    "create_legacy_registry",
]
