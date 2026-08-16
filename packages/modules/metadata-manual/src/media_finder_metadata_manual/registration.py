"""Static Manual metadata module registration."""

from __future__ import annotations

from collections.abc import Mapping
from importlib.resources import files

from media_finder_sdk import (
    MetadataEditor,
    MetadataProvider,
    MetadataProviderRegistration,
    MetadataRetentionPolicy,
    ProviderPayload,
    ResolvedModuleEnvironment,
    parse_manifest,
)

from .editor import ManualEditor
from .provider import ManualFixtureKey, ManualFixtures, ManualProvider
from .retention import ManualRetentionPolicy


def registration(
    *,
    fixtures: Mapping[ManualFixtureKey, ProviderPayload] | None = None,
) -> MetadataProviderRegistration:
    """Return a fresh typed registration; fixtures are for deterministic conformance."""

    manifest = parse_manifest(files(__package__).joinpath("module.toml").read_bytes())
    fixture_copy: ManualFixtures = dict(fixtures or {})

    def build(environment: ResolvedModuleEnvironment) -> MetadataProvider:
        if environment.names():
            raise ValueError("manual_environment_must_be_empty")
        return ManualProvider(fixture_copy)

    def retention() -> MetadataRetentionPolicy:
        return ManualRetentionPolicy()

    def editor(environment: ResolvedModuleEnvironment) -> MetadataEditor:
        if environment.names():
            raise ValueError("manual_environment_must_be_empty")
        return ManualEditor()

    return MetadataProviderRegistration(
        manifest=manifest,
        build=build,
        retention=retention,
        editor=editor,
    )


__all__: list[str] = []
