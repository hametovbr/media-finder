"""Typed registration and static registry foundation contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import pytest
from media_finder_sdk import (
    DownloadClientRegistration,
    MetadataProviderRegistration,
    ModuleKind,
    ReleaseProviderRegistration,
    StaticModuleRegistry,
    parse_manifest,
)

from .fixtures import manifest_toml


@dataclass(slots=True)
class _Closeable:
    closed: bool = False

    def close(self) -> None:
        self.closed = True


def _metadata(**overrides: object) -> MetadataProviderRegistration:
    manifest = parse_manifest(manifest_toml(**overrides))  # type: ignore[arg-type]
    return MetadataProviderRegistration(
        manifest=manifest,
        build=lambda _environment: _Closeable(),
        retention=lambda: _Closeable(),
    )


def test_registry_exposes_separate_immutable_typed_collections() -> None:
    metadata = _metadata()
    release = ReleaseProviderRegistration(
        manifest=parse_manifest(
            manifest_toml(
                module_id="example-release",
                module_kind=ModuleKind.RELEASE_PROVIDER,
                capabilities=("search", "resolve", "magnet"),
            )
        ),
        build=lambda _environment: _Closeable(),
    )
    download = DownloadClientRegistration(
        manifest=parse_manifest(
            manifest_toml(
                module_id="example-download",
                module_kind=ModuleKind.DOWNLOAD_CLIENT,
                capabilities=("destinations", "submit", "correlation", "magnet"),
            )
        ),
        build=lambda _environment: _Closeable(),
    )

    registry = StaticModuleRegistry.create(
        metadata=(metadata,), release=(release,), download=(download,)
    )

    assert tuple(registry.metadata) == ("example-metadata",)
    assert tuple(registry.release) == ("example-release",)
    assert tuple(registry.download) == ("example-download",)
    with pytest.raises(TypeError):
        cast(dict[str, object], registry.metadata)["other"] = metadata


def test_registry_rejects_duplicate_global_identity_and_wrong_typed_kind() -> None:
    first = _metadata()
    duplicate = _metadata()
    with pytest.raises(ValueError, match="module_identity_duplicate"):
        StaticModuleRegistry.create(metadata=(first, duplicate))

    wrong_kind = MetadataProviderRegistration(
        manifest=parse_manifest(
            manifest_toml(
                module_id="wrong-kind",
                module_kind=ModuleKind.RELEASE_PROVIDER,
                capabilities=("search", "resolve", "torrent"),
            )
        ),
        build=lambda _environment: _Closeable(),
        retention=lambda: _Closeable(),
    )
    with pytest.raises(ValueError, match="module_registration_kind_mismatch"):
        StaticModuleRegistry.create(metadata=(wrong_kind,))


@pytest.mark.parametrize(
    ("overrides", "code"),
    (
        ({"sdk_compatibility": ">=2,<3"}, "module_sdk_incompatible"),
        ({"contract_version": "2"}, "module_contract_unsupported"),
        ({"capabilities": ("search", "fetch")}, "module_capability_invalid"),
        (
            {"capabilities": ("search", "fetch", "normalize", "unknown")},
            "module_capability_invalid",
        ),
    ),
)
def test_registry_rejects_incompatible_contracts(overrides: dict[str, object], code: str) -> None:
    with pytest.raises(ValueError, match=code):
        StaticModuleRegistry.create(metadata=(_metadata(**overrides),))


def test_registry_rejects_conflicting_environment_classification() -> None:
    secret = _metadata(
        environment="""\
[[environment]]
name = "SHARED_VALUE"
required = true
secret = true
description_key = "module.example.token"
"""
    )
    public = _metadata(
        module_id="other-metadata",
        environment="""\
[[environment]]
name = "SHARED_VALUE"
required = true
secret = false
description_key = "module.example.token"
""",
    )
    with pytest.raises(ValueError, match="module_environment_conflict"):
        StaticModuleRegistry.create(metadata=(secret, public))
