"""Clean-wheel build, metadata, resource, and dependency-closure contracts."""

from __future__ import annotations

import email
import os
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pytest
from packaging.requirements import Requirement

ROOT = Path(__file__).parents[1]
UV = Path(shutil.which("uv") or ROOT / ".venv" / "Scripts" / "uv.exe")
UV_CACHE = ROOT / ".tools" / "uv-cache"
PRODUCT_VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()


@dataclass(frozen=True, slots=True)
class WheelSpec:
    import_name: str
    source_root: str
    workspace_dependencies: frozenset[str]
    required_resources: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class BuiltWheel:
    path: Path
    members: frozenset[str]
    metadata: email.message.Message


WHEEL_SPECS = {
    "media-finder": WheelSpec(
        "media_finder_server",
        "apps/server",
        frozenset(
            {
                "media-finder-builtin-ui",
                "media-finder-control-contracts",
                "media-finder-core",
                "media-finder-module-sdk",
                "media-finder-download-qbittorrent",
                "media-finder-metadata-manual",
                "media-finder-metadata-tmdb",
                "media-finder-release-prowlarr",
            }
        ),
    ),
    "media-finder-builtin-ui": WheelSpec(
        "media_finder_builtin_ui",
        "packages/builtin-ui",
        frozenset({"media-finder-control-contracts"}),
    ),
    "media-finder-control-contracts": WheelSpec(
        "media_finder_control", "packages/control-contracts", frozenset()
    ),
    "media-finder-core": WheelSpec(
        "media_finder_core",
        "packages/core",
        frozenset({"media-finder-control-contracts", "media-finder-module-sdk"}),
        frozenset(
            {
                "media_finder_core/_migration_resources/alembic.ini",
                "media_finder_core/_migration_resources/alembic/env.py",
                "media_finder_core/_migration_resources/alembic/script.py.mako",
                "media_finder_core/_migration_resources/alembic/versions/0001_clean_core.py",
            }
        ),
    ),
    "media-finder-module-sdk": WheelSpec("media_finder_sdk", "packages/module-sdk", frozenset()),
    "media-finder-download-qbittorrent": WheelSpec(
        "media_finder_download_qbittorrent",
        "packages/modules/download-qbittorrent",
        frozenset({"media-finder-module-sdk"}),
    ),
    "media-finder-metadata-manual": WheelSpec(
        "media_finder_metadata_manual",
        "packages/modules/metadata-manual",
        frozenset({"media-finder-module-sdk"}),
    ),
    "media-finder-metadata-tmdb": WheelSpec(
        "media_finder_metadata_tmdb",
        "packages/modules/metadata-tmdb",
        frozenset({"media-finder-module-sdk"}),
    ),
    "media-finder-release-prowlarr": WheelSpec(
        "media_finder_release_prowlarr",
        "packages/modules/release-prowlarr",
        frozenset({"media-finder-module-sdk"}),
    ),
}


def _clean_environment() -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.casefold()
        not in {"pythonhome", "pythonpath", "virtual_env", "uv_project_environment"}
    }
    environment["UV_CACHE_DIR"] = str(UV_CACHE)
    environment["UV_OFFLINE"] = "1"
    return environment


def _venv_python(root: Path) -> Path:
    windows = root / "Scripts" / "python.exe"
    return windows if windows.is_file() else root / "bin" / "python"


@pytest.fixture(scope="module")
def wheelhouse(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, BuiltWheel]]:
    scratch = tmp_path_factory.mktemp("workspace-wheels")
    destination = scratch / "wheelhouse"
    destination.mkdir()
    environment = _clean_environment()
    built: dict[str, BuiltWheel] = {}
    for distribution in WHEEL_SPECS:
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
        candidates = tuple(destination.glob(f"{distribution.replace('-', '_')}*.whl"))
        assert len(candidates) == 1, (distribution, candidates)
        with zipfile.ZipFile(candidates[0]) as archive:
            members = frozenset(archive.namelist())
            metadata_member = next(name for name in members if name.endswith(".dist-info/METADATA"))
            metadata = email.message_from_bytes(archive.read(metadata_member))
        built[distribution] = BuiltWheel(candidates[0], members, metadata)
        repeated = scratch / "repeated" / distribution
        repeated.mkdir(parents=True)
        subprocess.run(
            [
                str(UV),
                "build",
                "--wheel",
                "--package",
                distribution,
                "--out-dir",
                str(repeated),
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )
        repeated_wheel = next(repeated.glob("*.whl"))
        assert repeated_wheel.read_bytes() == candidates[0].read_bytes(), distribution
    return scratch, built


@pytest.mark.parametrize("distribution", tuple(WHEEL_SPECS))
def test_every_workspace_wheel_has_lockstep_metadata_and_complete_package_data(
    distribution: str,
    wheelhouse: tuple[Path, dict[str, BuiltWheel]],
) -> None:
    _, built = wheelhouse
    spec = WHEEL_SPECS[distribution]
    wheel = built[distribution]
    package_root = spec.import_name.replace(".", "/")
    requirements = tuple(wheel.metadata.get_all("Requires-Dist", []))
    workspace_requirements = {
        Requirement(value).name.casefold()
        for value in requirements
        if Requirement(value).name.casefold() in WHEEL_SPECS
    }

    assert wheel.metadata["Version"] == PRODUCT_VERSION
    assert f"{package_root}/__init__.py" in wheel.members
    assert f"{package_root}/py.typed" in wheel.members
    assert not any("__pycache__" in member or member.endswith(".pyc") for member in wheel.members)
    assert workspace_requirements == spec.workspace_dependencies
    assert spec.required_resources <= wheel.members
    if distribution == "media-finder":
        member_roots = {member.partition("/")[0] for member in wheel.members}
        assert member_roots == {
            "media_finder_server",
            *{root for root in member_roots if root.endswith(".dist-info")},
        }


def test_ui_and_module_wheels_contain_their_complete_non_python_resource_inventory(
    wheelhouse: tuple[Path, dict[str, BuiltWheel]],
) -> None:
    _, built = wheelhouse
    resource_packages = {
        "media-finder-builtin-ui": ROOT / "packages/builtin-ui/src/media_finder_builtin_ui",
        "media-finder-download-qbittorrent": ROOT
        / "packages/modules/download-qbittorrent/src/media_finder_download_qbittorrent",
        "media-finder-metadata-manual": ROOT
        / "packages/modules/metadata-manual/src/media_finder_metadata_manual",
        "media-finder-metadata-tmdb": ROOT
        / "packages/modules/metadata-tmdb/src/media_finder_metadata_tmdb",
        "media-finder-release-prowlarr": ROOT
        / "packages/modules/release-prowlarr/src/media_finder_release_prowlarr",
    }
    for distribution, source in resource_packages.items():
        package_root = WHEEL_SPECS[distribution].import_name
        expected = {
            f"{package_root}/{path.relative_to(source).as_posix()}"
            for path in source.rglob("*")
            if path.is_file()
            and path.suffix not in {".py", ".pyc"}
            and "__pycache__" not in path.parts
        }
        assert expected <= built[distribution].members, distribution


def _workspace_closure(distribution: str) -> set[str]:
    closure = {distribution}
    pending = [distribution]
    while pending:
        current = pending.pop()
        for dependency in WHEEL_SPECS[current].workspace_dependencies:
            if dependency not in closure:
                closure.add(dependency)
                pending.append(dependency)
    return closure


@pytest.mark.parametrize("distribution", tuple(WHEEL_SPECS))
def test_each_wheel_installs_with_only_its_declared_workspace_dependency_closure(
    distribution: str,
    wheelhouse: tuple[Path, dict[str, BuiltWheel]],
    tmp_path: Path,
) -> None:
    scratch, built = wheelhouse
    environment = _clean_environment()
    virtual_environment = tmp_path / "venv"
    subprocess.run(
        [str(UV), "venv", "--python", "3.13", str(virtual_environment)],
        cwd=scratch,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    python = _venv_python(virtual_environment)
    constraints = scratch / "constraints.txt"
    if not constraints.exists():
        exported = subprocess.run(
            [
                str(UV),
                "export",
                "--frozen",
                "--package",
                "media-finder",
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
        constraints.write_text(exported.stdout, encoding="utf-8")
    subprocess.run(
        [
            str(UV),
            "pip",
            "install",
            "--python",
            str(python),
            "--constraint",
            str(constraints),
            "--find-links",
            str(scratch / "wheelhouse"),
            str(built[distribution].path),
        ],
        cwd=scratch,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    probe = "\n".join(
        (
            "import importlib",
            "import importlib.metadata",
            "import importlib.util",
            "import pathlib",
            f"module = importlib.import_module({WHEEL_SPECS[distribution].import_name!r})",
            "origin = pathlib.Path(module.__file__).resolve()",
            f"venv = pathlib.Path({str(virtual_environment)!r}).resolve()",
            "assert origin.is_relative_to(venv), (origin, venv)",
            "assert hasattr(module, '__all__')",
            f"workspace = {set(WHEEL_SPECS)!r}",
            "distributions = importlib.metadata.distributions()",
            "installed = {item.metadata['Name'].casefold() for item in distributions}",
            f"expected = {_workspace_closure(distribution)!r}",
            "assert installed & workspace == expected, (installed & workspace, expected)",
            "assert importlib.util.find_spec('media_finder') is None",
            *(
                (
                    "from media_finder_core.platform import migrate_to_head",
                    "migrate_to_head('sqlite:///wheel-migration.db')",
                    "assert pathlib.Path('wheel-migration.db').is_file()",
                )
                if distribution == "media-finder-core"
                else ()
            ),
        )
    )
    subprocess.run(
        [str(python), "-I", "-c", probe],
        cwd=scratch,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
