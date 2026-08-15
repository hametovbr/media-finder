"""Static qBittorrent download-client registration."""

from __future__ import annotations

from collections.abc import Callable
from importlib.resources import files

import httpx
from media_finder_sdk import (
    DownloadClient,
    DownloadClientRegistration,
    ResolvedModuleEnvironment,
    parse_manifest,
)

from .client import QbittorrentClient
from .transport import QbittorrentTransport


def registration(
    *,
    client_factory: Callable[[], httpx.Client] = httpx.Client,
) -> DownloadClientRegistration:
    manifest = parse_manifest(files(__package__).joinpath("module.toml").read_bytes())

    def build(environment: ResolvedModuleEnvironment) -> DownloadClient:
        client = client_factory()
        try:
            return QbittorrentClient(QbittorrentTransport(environment=environment, client=client))
        except BaseException:
            client.close()
            raise

    return DownloadClientRegistration(manifest=manifest, build=build)


__all__: list[str] = []
