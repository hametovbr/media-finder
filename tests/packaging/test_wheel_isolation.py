"""Isolated build contract for the modular workspace foundations."""

from __future__ import annotations

from pathlib import Path

import pytest

from ._wheel import assert_isolated_import, build_wheel


@pytest.mark.parametrize(
    ("distribution", "import_name", "source_root", "expected_dependencies"),
    (
        (
            "media-finder",
            "media_finder_server",
            "apps/server",
            {
                "media-finder-core",
                "media-finder-control-contracts",
                "media-finder-builtin-ui",
            },
        ),
        (
            "media-finder-core",
            "media_finder_core",
            "packages/core",
            {"media-finder-module-sdk", "media-finder-control-contracts"},
        ),
        (
            "media-finder-module-sdk",
            "media_finder_sdk",
            "packages/module-sdk",
            {"pydantic", "packaging"},
        ),
    ),
)
def test_foundation_wheel_builds_and_imports_without_source_tree_leakage(
    distribution: str,
    import_name: str,
    source_root: str,
    expected_dependencies: set[str],
    tmp_path: Path,
) -> None:
    assert (Path(__file__).parents[2] / source_root / "pyproject.toml").is_file()
    wheel = build_wheel(distribution, tmp_path / "wheels")
    normalized_import_path = import_name.replace(".", "/")

    assert f"{normalized_import_path}/__init__.py" in wheel.members
    assert f"{normalized_import_path}/py.typed" in wheel.members
    requirements = tuple(wheel.metadata.get_all("Requires-Dist", []))
    assert all(
        any(requirement.lower().startswith(expected.lower()) for requirement in requirements)
        for expected in expected_dependencies
    )
    assert_isolated_import(wheel, import_name, tmp_path / "installed")
