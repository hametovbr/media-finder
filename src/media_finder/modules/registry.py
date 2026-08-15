"""The single compile-time composition boundary for first-party modules."""

from collections.abc import Mapping
from typing import Any, cast

from pydantic import ValidationError

from ..sdk.protocols import DownloadClient, MetadataProvider
from ..sdk.registration import (
    DownloadClientRegistration,
    HttpClientFactory,
    MetadataProviderRegistration,
    SecretResolver,
    StaticModuleRegistry,
)
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
    config = TmdbConfig.model_validate(payload)
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
    config = QbittorrentConfig.model_validate(payload)
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
        ),
        "tmdb": MetadataProviderRegistration(
            key="tmdb",
            config_model=TmdbConfig,
            retention_factory=lambda: cast(MetadataProvider, TmdbProvider.retention_only()),
            build=_build_tmdb,
        ),
    },
    download_clients={
        "qbittorrent": DownloadClientRegistration(
            key="qbittorrent",
            config_model=QbittorrentConfig,
            build=_build_qbittorrent,
        )
    },
)


def normalize_download_client_config(module_key: str, payload: dict[str, object]) -> dict[str, Any]:
    registration = FIRST_PARTY_MODULES.download_clients.get(module_key)
    if registration is None:
        raise ValueError("download_client_module_unknown")
    try:
        validated = registration.config_model.model_validate(payload)
    except ValidationError:
        raise ValueError("download_client_configuration_invalid") from None
    return validated.model_dump(mode="json")
