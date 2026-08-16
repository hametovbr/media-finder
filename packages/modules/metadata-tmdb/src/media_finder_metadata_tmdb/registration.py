"""Static TMDB metadata module registration."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from importlib.resources import files

import httpx
from media_finder_sdk import (
    MetadataProvider,
    MetadataProviderRegistration,
    MetadataRetentionPolicy,
    ResolvedModuleEnvironment,
    parse_manifest,
)

from .provider import TmdbProvider
from .retention import TmdbRetentionPolicy
from .transport import TmdbTransport


def _utc_now() -> datetime:
    return datetime.now(UTC)


def registration(
    *,
    client_factory: Callable[[], httpx.Client] = httpx.Client,
    clock: Callable[[], datetime] = _utc_now,
) -> MetadataProviderRegistration:
    """Return a typed TMDB registration with module-owned HTTP resources."""

    manifest = parse_manifest(files(__package__).joinpath("module.toml").read_bytes())

    def build(environment: ResolvedModuleEnvironment) -> MetadataProvider:
        client = client_factory()
        try:
            transport = TmdbTransport(environment=environment, client=client)
            return TmdbProvider(transport, clock)
        except BaseException:
            client.close()
            raise

    def retention() -> MetadataRetentionPolicy:
        return TmdbRetentionPolicy()

    return MetadataProviderRegistration(
        manifest=manifest,
        build=build,
        retention=retention,
    )


__all__: list[str] = []
