"""The single compile-time composition boundary for first-party modules."""

from collections.abc import Mapping
from typing import cast

from pydantic import HttpUrl

from ..sdk.protocols import DownloadClient, MetadataProvider
from ..sdk.registration import (
    DownloadClientRegistration,
    HttpClientFactory,
    MetadataProviderRegistration,
    SecretResolver,
    StaticModuleRegistry,
)
from ..sdk.settings import EnvReference
from ..sdk.types import EnvironmentVariableSpec
from .manual import ManualConfig, ManualProvider
from .qbittorrent import (
    HttpxQbittorrentTransport,
    QbittorrentClient,
    QbittorrentConfig,
)
from .tmdb import HttpxTmdbTransport, TmdbConfig, TmdbProvider


def _build_tmdb(
    payload: Mapping[str, object],
    http_client: HttpClientFactory,
    secret_resolver: SecretResolver,
) -> MetadataProvider:
    config = TmdbConfig(api_token=EnvReference(value="env:TMDB_TOKEN"))
    return cast(
        MetadataProvider,
        TmdbProvider(
            config,
            HttpxTmdbTransport(
                str(config.base_url), config.api_token.value, secret_resolver, http_client()
            ),
        ),
    )


def _build_manual(
    payload: Mapping[str, object],
    http_client: HttpClientFactory,
    secret_resolver: SecretResolver,
) -> MetadataProvider:
    del http_client, secret_resolver
    ManualConfig.model_validate(payload)
    return cast(MetadataProvider, ManualProvider())


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
            retention_factory=lambda: cast(MetadataProvider, ManualProvider()),
            build=_build_manual,
            environment=(),
        ),
        "tmdb": MetadataProviderRegistration(
            key="tmdb",
            config_model=TmdbConfig,
            retention_factory=lambda: cast(MetadataProvider, TmdbProvider.retention_only()),
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
