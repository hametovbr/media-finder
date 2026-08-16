"""Resolved environment secrecy and immutability contracts."""

from __future__ import annotations

import pytest
from media_finder_sdk import (
    ModuleError,
    ModuleManifest,
    parse_manifest,
    resolve_module_environment,
)

from .fixtures import manifest_toml


def _manifest() -> ModuleManifest:
    return parse_manifest(
        manifest_toml(
            environment="""\
[[environment]]
name = "EXAMPLE_TOKEN"
required = true
secret = true
description_key = "module.example.token"

[[environment]]
name = "EXAMPLE_URL"
required = false
secret = false
description_key = "module.example.token"
"""
        )
    )


def test_resolved_values_are_exact_immutable_and_redacted() -> None:
    source = {
        "EXAMPLE_TOKEN": "token-value",
        "EXAMPLE_URL": "https://example.test/api",
        "UNDECLARED_SECRET": "must-not-be-reachable",
    }
    resolved = resolve_module_environment(_manifest(), source)
    source["EXAMPLE_TOKEN"] = "changed-after-resolution"

    assert resolved.names() == ("EXAMPLE_TOKEN", "EXAMPLE_URL")
    assert resolved.require("EXAMPLE_TOKEN") == "token-value"
    assert resolved.optional("EXAMPLE_URL") == "https://example.test/api"
    assert resolved.optional("UNDECLARED_SECRET") is None
    assert "token-value" not in repr(resolved)
    assert "https://example.test/api" not in repr(resolved)
    assert "must-not-be-reachable" not in repr(resolved)
    assert not hasattr(resolved, "model_dump")
    assert not hasattr(resolved, "as_dict")
    with pytest.raises(AttributeError):
        resolved.require("UNDECLARED_SECRET")


def test_missing_required_value_raises_only_a_safe_stable_failure() -> None:
    with pytest.raises(ModuleError) as captured:
        resolve_module_environment(_manifest(), {"EXAMPLE_TOKEN": ""})

    assert captured.value.code == "module_environment_missing"
    assert captured.value.safe_details == {"missing_names": ("EXAMPLE_TOKEN",)}
    assert str(captured.value) == "module_environment_missing"
    assert "token-value" not in repr(captured.value)
