"""Isolated build contract for the modular workspace foundations."""

from __future__ import annotations

import email
import os
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
UV = Path(shutil.which("uv") or ROOT / ".venv" / "Scripts" / "uv.exe")
UV_CACHE = ROOT / ".tools" / "uv-cache"


@dataclass(frozen=True, slots=True)
class BuiltWheel:
    path: Path
    members: frozenset[str]
    metadata: email.message.Message


def _build_wheel(distribution: str, destination: Path) -> BuiltWheel:
    destination.mkdir(parents=True, exist_ok=True)
    environment = {**os.environ, "UV_CACHE_DIR": str(UV_CACHE)}
    completed = subprocess.run(
        [
            str(UV),
            "build",
            "--wheel",
            "--no-build-isolation",
            "--package",
            distribution,
            "--out-dir",
            str(destination),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    wheels = tuple(destination.glob("*.whl"))
    assert len(wheels) == 1, wheels

    with zipfile.ZipFile(wheels[0]) as archive:
        members = frozenset(archive.namelist())
        metadata_member = next(name for name in members if name.endswith(".dist-info/METADATA"))
        metadata = email.message_from_bytes(archive.read(metadata_member))
    return BuiltWheel(path=wheels[0], members=members, metadata=metadata)


def _assert_isolated_import(wheel: BuiltWheel, import_name: str, target: Path) -> None:
    environment = {**os.environ, "UV_CACHE_DIR": str(UV_CACHE)}
    subprocess.run(
        [str(UV), "pip", "install", "--target", str(target), "--no-deps", str(wheel.path)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    probe = "\n".join(
        (
            "import importlib",
            "import pathlib",
            "import sys",
            f"target = pathlib.Path({str(target)!r}).resolve()",
            "sys.path.insert(0, str(target))",
            f"module = importlib.import_module({import_name!r})",
            "origin = pathlib.Path(module.__file__).resolve()",
            "assert origin.is_relative_to(target), (origin, target)",
            "assert hasattr(module, '__all__')",
        )
    )
    subprocess.run(
        [sys.executable, "-I", "-c", probe],
        cwd=target,
        check=True,
        capture_output=True,
        text=True,
    )


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
    assert (ROOT / source_root / "pyproject.toml").is_file()
    wheel = _build_wheel(distribution, tmp_path / "wheels")
    normalized_import_path = import_name.replace(".", "/")

    assert f"{normalized_import_path}/__init__.py" in wheel.members
    assert f"{normalized_import_path}/py.typed" in wheel.members
    requirements = tuple(wheel.metadata.get_all("Requires-Dist", []))
    assert all(
        any(requirement.lower().startswith(expected.lower()) for requirement in requirements)
        for expected in expected_dependencies
    )
    _assert_isolated_import(wheel, import_name, tmp_path / "installed")
