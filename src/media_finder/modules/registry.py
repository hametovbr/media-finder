"""The single compile-time composition boundary for first-party modules."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import cast

from media_finder_metadata_manual import registration as manual_registration
from media_finder_metadata_tmdb import registration as tmdb_registration
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
    MediaKind as SDKMediaKind,
)
from media_finder_sdk import MetadataProvider as SDKMetadataProvider
from media_finder_sdk import MetadataRetentionPolicy as SDKMetadataRetentionPolicy
from media_finder_sdk import (
    NormalizedMetadata as SDKNormalizedMetadata,
)
from media_finder_sdk import (
    RetentionPolicy as SDKRetentionPolicy,
)
from media_finder_sdk import (
    RetentionSubject as SDKRetentionSubject,
)
from pydantic import BaseModel, ConfigDict, HttpUrl

from ..sdk.errors import ModuleError
from ..sdk.protocols import DownloadClient, MetadataProvider
from ..sdk.registration import (
    DownloadClientRegistration,
    HttpClientFactory,
    MetadataProviderRegistration,
    SecretResolver,
    StaticModuleRegistry,
)
from ..sdk.types import (
    Attribution,
    EnvironmentVariableSpec,
    ExportWarning,
    MediaKind,
    MetadataSearchResult,
    ModuleManifest,
    NormalizedMetadata,
    RetentionAction,
    RetentionActionKind,
    RetentionPolicy,
)
from .qbittorrent import (
    HttpxQbittorrentTransport,
    QbittorrentClient,
    QbittorrentConfig,
)


class ManualConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


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
    manifest = ModuleManifest(
        key="manual",
        version="1.0.0",
        contract_version="1",
        name_key="module.manual.name",
        capabilities=frozenset({"search", "fetch", "normalize", "metadata-edit"}),
        translation_keys={"module.manual.name": "Manual"},
    )
    config_model = ManualConfig

    def __init__(self) -> None:
        registered = manual_registration()
        environment = resolve_module_environment(registered.manifest, {})
        if registered.editor is None:
            raise ValueError("manual_editor_missing")
        self._provider = registered.build(environment)
        self._retention = registered.retention()
        self._editor = registered.editor(environment)

    def validate_config(self) -> None:
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
                provider_id="manual",
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
                provider_id="manual",
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
        return Attribution(provider_key="manual", notice="User-provided metadata")

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
        self._editor.close()
        self._provider.close()
        self._retention.close()


def _build_manual(
    payload: Mapping[str, object],
    http_client: HttpClientFactory,
    secret_resolver: SecretResolver,
) -> MetadataProvider:
    del http_client, secret_resolver
    ManualConfig.model_validate(payload)
    return cast(MetadataProvider, _LegacyManualAdapter())


class TmdbConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _LegacyTmdbAdapter:
    manifest = ModuleManifest(
        key="tmdb",
        version="0.1.0",
        contract_version="1",
        name_key="module.tmdb.name",
        capabilities=frozenset({"search", "fetch", "normalize", "retention"}),
        translation_keys={"module.tmdb.name": "TMDB"},
    )
    config_model = TmdbConfig

    def __init__(
        self,
        provider: SDKMetadataProvider | None,
        retention: SDKMetadataRetentionPolicy,
    ) -> None:
        self._provider = provider
        self._retention = retention

    @classmethod
    def retention_only(cls) -> _LegacyTmdbAdapter:
        return cls(None, tmdb_registration().retention())

    def validate_config(self) -> None:
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
            provider_key="tmdb",
            notice="This product uses the TMDB API but is not endorsed or certified by TMDB.",
            url=HttpUrl("https://www.themoviedb.org/"),
        )

    def retention_for(self, created_at: datetime) -> RetentionPolicy:
        policy = self._retention.retention_for(created_at)
        return RetentionPolicy.model_validate(policy.model_dump(mode="json"))

    def plan_retention(self, policy: RetentionPolicy, now: datetime) -> RetentionAction:
        sdk_policy = _to_sdk_retention(policy)
        action = self._retention.plan(
            _tmdb_retention_subject(sdk_policy),
            now,
        )
        return RetentionAction.model_validate(action.model_dump(mode="json"))

    def export_warning(self, policy: RetentionPolicy, now: datetime) -> ExportWarning | None:
        warning = self._retention.export_warning(_to_sdk_retention(policy), now)
        if warning is None:
            return None
        return ExportWarning.model_validate(warning.model_dump(mode="json"))

    def close(self) -> None:
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

    @staticmethod
    def _identity(kind: str, external_id: str, locale: str) -> MetadataIdentity:
        return MetadataIdentity(
            provider_id="tmdb",
            external_id=external_id,
            media_kind=SDKMediaKind(kind),
            locale=locale,
        )


def _to_sdk_retention(policy: RetentionPolicy) -> SDKRetentionPolicy:
    return SDKRetentionPolicy.model_validate(policy.model_dump(mode="json"))


def _tmdb_retention_subject(policy: SDKRetentionPolicy) -> SDKRetentionSubject:
    return SDKRetentionSubject(
        identity=MetadataIdentity(
            provider_id="tmdb",
            external_id="0",
            media_kind=SDKMediaKind.MOVIE,
            locale="en",
        ),
        policy=policy,
    )


def _build_tmdb(
    payload: Mapping[str, object],
    http_client: HttpClientFactory,
    secret_resolver: SecretResolver,
) -> MetadataProvider:
    del secret_resolver
    registered = tmdb_registration(client_factory=http_client)
    environment = resolve_module_environment(
        registered.manifest,
        {name: str(value) for name, value in payload.items()},
    )
    return cast(
        MetadataProvider,
        _LegacyTmdbAdapter(registered.build(environment), registered.retention()),
    )


def _build_qbittorrent(
    payload: Mapping[str, object],
    http_client: HttpClientFactory,
    secret_resolver: SecretResolver,
) -> DownloadClient:
    config = QbittorrentConfig(
        base_url=HttpUrl(str(payload["QBITTORRENT_URL"])),
        username_ref="env:QBITTORRENT_USERNAME",
        password_ref="env:QBITTORRENT_PASSWORD",
    )
    return cast(
        DownloadClient,
        QbittorrentClient(
            config,
            HttpxQbittorrentTransport(str(config.base_url), http_client()),
            secret_resolver,
        ),
    )


FIRST_PARTY_MODULES = StaticModuleRegistry(
    metadata_providers={
        "manual": MetadataProviderRegistration(
            key="manual",
            config_model=ManualConfig,
            retention_factory=lambda: cast(MetadataProvider, _LegacyManualAdapter()),
            build=_build_manual,
            environment=(),
        ),
        "tmdb": MetadataProviderRegistration(
            key="tmdb",
            config_model=TmdbConfig,
            retention_factory=lambda: cast(MetadataProvider, _LegacyTmdbAdapter.retention_only()),
            build=_build_tmdb,
            environment=(
                EnvironmentVariableSpec(
                    name="TMDB_TOKEN",
                    required=True,
                    secret=True,
                    description_key="module.tmdb.environment.token",
                ),
            ),
        ),
    },
    download_clients={
        "qbittorrent": DownloadClientRegistration(
            key="qbittorrent",
            config_model=QbittorrentConfig,
            build=_build_qbittorrent,
            environment=(
                EnvironmentVariableSpec(
                    name="QBITTORRENT_URL",
                    required=True,
                    secret=False,
                    description_key="module.qbittorrent.environment.url",
                ),
                EnvironmentVariableSpec(
                    name="QBITTORRENT_USERNAME",
                    required=True,
                    secret=True,
                    description_key="module.qbittorrent.environment.username",
                ),
                EnvironmentVariableSpec(
                    name="QBITTORRENT_PASSWORD",
                    required=True,
                    secret=True,
                    description_key="module.qbittorrent.environment.password",
                ),
            ),
        )
    },
)
