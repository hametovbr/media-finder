"""Manifest parsing and validation contracts."""

from __future__ import annotations

from pathlib import Path

import pytest
from media_finder_sdk import ModuleKind, load_manifest, parse_manifest
from pydantic import ValidationError

from .fixtures import manifest_toml


def test_value_free_manifest_exposes_static_module_contract(tmp_path: Path) -> None:
    path = tmp_path / "module.toml"
    path.write_bytes(
        manifest_toml(
            environment="""\
[[environment]]
name = "EXAMPLE_TOKEN"
required = true
secret = true
description_key = "module.example.token"
"""
        )
    )

    manifest = load_manifest(path)

    assert manifest.module_id == "example-metadata"
    assert manifest.module_kind is ModuleKind.METADATA_PROVIDER
    assert manifest.module_version == "1.2.3"
    assert manifest.sdk_compatibility == ">=1,<2"
    assert manifest.contract_version == "1"
    assert manifest.capabilities == frozenset({"search", "fetch", "normalize"})
    assert manifest.environment[0].name == "EXAMPLE_TOKEN"
    assert manifest.attribution is not None
    assert str(manifest.attribution.url) == "https://example.test/credits"
    assert "token-value" not in repr(manifest)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("module_id", "Invalid ID"),
        ("module_version", "1.0"),
        ("module_version", "01.0.0"),
        ("sdk_compatibility", "not-a-range"),
    ),
)
def test_invalid_identity_version_or_sdk_range_is_rejected(field: str, value: str) -> None:
    arguments = {field: value}
    with pytest.raises(ValidationError):
        parse_manifest(manifest_toml(**arguments))  # type: ignore[arg-type]


@pytest.mark.parametrize("name", ("", "token", "PREFIX_*", "1TOKEN", "TOKEN-NAME"))
def test_environment_names_are_exact_and_syntactically_valid(name: str) -> None:
    declaration = f'''\
[[environment]]
name = "{name}"
required = true
secret = true
description_key = "module.example.token"
'''
    with pytest.raises(ValidationError):
        parse_manifest(manifest_toml(environment=declaration))


def test_duplicate_environment_declaration_and_runtime_values_are_rejected() -> None:
    duplicate = """\
[[environment]]
name = "EXAMPLE_TOKEN"
required = true
secret = true
description_key = "module.example.token"

[[environment]]
name = "EXAMPLE_TOKEN"
required = true
secret = true
description_key = "module.example.token"
"""
    with pytest.raises(ValidationError, match="environment_variable_duplicate"):
        parse_manifest(manifest_toml(environment=duplicate))

    with pytest.raises(ValidationError):
        parse_manifest(manifest_toml() + b'\nresolved_token = "token-value"\n')


def test_declared_translation_keys_cover_manifest_descriptions() -> None:
    missing_translation = manifest_toml(
        environment="""\
[[environment]]
name = "EXAMPLE_TOKEN"
required = true
secret = true
description_key = "module.example.unknown"
"""
    )
    with pytest.raises(ValidationError, match="translation_key_undeclared"):
        parse_manifest(missing_translation)
