"""Declared-environment resolution for module construction."""

from __future__ import annotations

from collections.abc import Mapping

from media_finder_sdk import (
    ModuleManifest,
    ResolvedModuleEnvironment,
    resolve_module_environment,
)


class _EnvironmentResolver:
    """Capture the process environment and expose only manifest-declared values."""

    def __init__(self, environment: Mapping[str, str]) -> None:
        self._environment = dict(environment)

    def resolve(self, manifest: ModuleManifest) -> ResolvedModuleEnvironment:
        return resolve_module_environment(manifest, self._environment)


__all__: list[str] = []
