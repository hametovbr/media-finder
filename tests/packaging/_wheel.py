"""Build and import wheels without leaking repository source paths."""

from __future__ import annotations

import email
import os
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).parents[2]
UV = Path(shutil.which("uv") or ROOT / ".venv" / "Scripts" / "uv.exe")
UV_CACHE = ROOT / ".tools" / "uv-cache"


@dataclass(frozen=True, slots=True)
class BuiltWheel:
    path: Path
    members: frozenset[str]
    metadata: email.message.Message


def build_wheel(distribution: str, destination: Path) -> BuiltWheel:
    destination.mkdir(parents=True, exist_ok=True)
    environment = {**os.environ, "UV_CACHE_DIR": str(UV_CACHE)}
    completed = subprocess.run(
        [
            str(UV),
            "build",
            "--wheel",
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


def assert_isolated_import(wheel: BuiltWheel, import_name: str, target: Path) -> None:
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
