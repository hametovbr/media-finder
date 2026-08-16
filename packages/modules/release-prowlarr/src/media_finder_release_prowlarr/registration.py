"""Static Prowlarr release-provider registration."""

from __future__ import annotations

from collections.abc import Callable
from importlib.resources import files

import httpx
from media_finder_sdk import (
    ReleaseProvider,
    ReleaseProviderRegistration,
    ResolvedModuleEnvironment,
    parse_manifest,
)

from .provider import ProwlarrProvider
from .transport import ProwlarrLimits, ProwlarrTransport


def registration(
    *,
    client_factory: Callable[[], httpx.Client] = httpx.Client,
    limits: ProwlarrLimits | None = None,
) -> ReleaseProviderRegistration:
    manifest = parse_manifest(files(__package__).joinpath("module.toml").read_bytes())
    resolved_limits = limits or ProwlarrLimits()

    def build(environment: ResolvedModuleEnvironment) -> ReleaseProvider:
        client = client_factory()
        try:
            return ProwlarrProvider(
                ProwlarrTransport(
                    environment=environment,
                    client=client,
                    limits=resolved_limits,
                )
            )
        except BaseException:
            client.close()
            raise

    return ReleaseProviderRegistration(manifest=manifest, build=build)


__all__: list[str] = []
