"""Build and exercise the built-in UI in a wheel-only virtual environment."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parents[3]
PACKAGE = ROOT / "packages" / "builtin-ui"
TESTS = PACKAGE / "tests"
UV = Path(shutil.which("uv") or ROOT / ".venv" / "Scripts" / "uv.exe")
PROHIBITED_IMPORTS = (
    "alembic",
    "media_finder_core",
    "media_finder_server",
    "media_finder_sdk",
    "media_finder_metadata_manual",
    "media_finder_metadata_tmdb",
    "media_finder_release_prowlarr",
    "media_finder_download_qbittorrent",
    "sqlalchemy",
)


def _run(arguments: list[str], *, cwd: Path, environment: dict[str, str]) -> None:
    subprocess.run(arguments, cwd=cwd, env=environment, check=True)


def _venv_python(environment_root: Path) -> Path:
    windows = environment_root / "Scripts" / "python.exe"
    return windows if windows.exists() else environment_root / "bin" / "python"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("suite", choices=("unit",))
    parser.parse_args()
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.casefold() not in {"pythonpath", "pythonhome", "virtual_env"}
    }
    environment["UV_CACHE_DIR"] = str(ROOT / ".tools" / "uv-cache")

    with tempfile.TemporaryDirectory(prefix="media-finder-ui-") as directory:
        scratch = Path(directory)
        wheels = scratch / "wheels"
        wheels.mkdir()
        for distribution in (
            "media-finder-control-contracts",
            "media-finder-builtin-ui",
        ):
            _run(
                [
                    str(UV),
                    "build",
                    "--wheel",
                    "--package",
                    distribution,
                    "--out-dir",
                    str(wheels),
                ],
                cwd=ROOT,
                environment=environment,
            )

        virtual_environment = scratch / "venv"
        _run(
            [str(UV), "venv", "--python", sys.executable, str(virtual_environment)],
            cwd=scratch,
            environment=environment,
        )
        python = _venv_python(virtual_environment)
        requirements = scratch / "requirements.txt"
        exported = subprocess.run(
            [
                str(UV),
                "export",
                "--frozen",
                "--package",
                "media-finder-builtin-ui",
                "--group",
                "test",
                "--no-dev",
                "--no-hashes",
                "--no-emit-project",
                "--no-emit-workspace",
            ],
            cwd=ROOT,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        requirements.write_text(exported.stdout, encoding="utf-8")
        _run(
            [str(UV), "pip", "install", "--python", str(python), "-r", str(requirements)],
            cwd=scratch,
            environment=environment,
        )
        _run(
            [
                str(UV),
                "pip",
                "install",
                "--python",
                str(python),
                "--no-deps",
                *(str(path) for path in sorted(wheels.glob("*.whl"))),
            ],
            cwd=scratch,
            environment=environment,
        )

        probe = (
            "import importlib.util\n"
            "from importlib.resources import files\n"
            f"for name in {PROHIBITED_IMPORTS!r}:\n"
            "    assert importlib.util.find_spec(name) is None, name\n"
            "root = files('media_finder_builtin_ui')\n"
            "assert root.joinpath('static/index.html').is_file()\n"
            "assets = tuple(root.joinpath('static/assets').iterdir())\n"
            "assert any(\n"
            "    path.name.startswith('index-') and path.name.endswith('.js')\n"
            "    for path in assets\n"
            ")\n"
            "assert any(\n"
            "    path.name.startswith('index-') and path.name.endswith('.css')\n"
            "    for path in assets\n"
            ")\n"
        )
        _run([str(python), "-I", "-c", probe], cwd=scratch, environment=environment)

        discovered = sorted(TESTS.rglob("test_*.py"))
        _run(
            [
                str(python),
                "-m",
                "pytest",
                "-c",
                str(PACKAGE / "pyproject.toml"),
                "-p",
                "no:cacheprovider",
                *(str(path) for path in discovered),
            ],
            cwd=scratch,
            environment=environment,
        )


if __name__ == "__main__":
    main()
