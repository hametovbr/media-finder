"""Executable dependency rules for the package-enforced modular monolith."""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path

from packaging.requirements import Requirement

ROOT = Path(__file__).parents[2]

PACKAGES = {
    "server": ROOT / "apps" / "server",
    "core": ROOT / "packages" / "core",
    "sdk": ROOT / "packages" / "module-sdk",
    "control": ROOT / "packages" / "control-contracts",
    "ui": ROOT / "packages" / "builtin-ui",
    "manual": ROOT / "packages" / "modules" / "metadata-manual",
    "tmdb": ROOT / "packages" / "modules" / "metadata-tmdb",
    "prowlarr": ROOT / "packages" / "modules" / "release-prowlarr",
    "qbittorrent": ROOT / "packages" / "modules" / "download-qbittorrent",
}


def _project(directory: Path) -> dict[str, object]:
    manifest = directory / "pyproject.toml"
    assert manifest.is_file(), f"missing isolated distribution: {manifest.relative_to(ROOT)}"
    parsed = tomllib.loads(manifest.read_text(encoding="utf-8"))
    return parsed["project"]


def _imports(directory: Path) -> list[tuple[Path, int, str]]:
    found: list[tuple[Path, int, str]] = []
    for path in sorted((directory / "src").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.extend((path, node.lineno, alias.name) for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.append((path, node.lineno, node.module))
    return found


def test_root_is_a_virtual_workspace_with_every_distribution_declared() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert "project" not in config, "the root must not remain an installable backend package"
    assert config["tool"]["uv"]["workspace"]["members"] == [
        "apps/*",
        "packages/*",
        "packages/modules/*",
    ]
    assert all((path / "pyproject.toml").is_file() for path in PACKAGES.values())


def test_distribution_dependencies_follow_the_approved_graph() -> None:
    projects = {name: _project(path) for name, path in PACKAGES.items()}
    dependencies = {
        name: set(project.get("dependencies", [])) for name, project in projects.items()
    }

    assert dependencies["sdk"] <= {"pydantic>=2.11,<3", "packaging>=24,<26"}
    assert dependencies["control"] == {"pydantic>=2.11,<3"}
    assert "media-finder-control-contracts" in dependencies["ui"]
    assert "media-finder-core" not in dependencies["ui"]
    assert "media-finder-module-sdk" in dependencies["core"]
    assert "media-finder-control-contracts" in dependencies["core"]

    for module in ("manual", "tmdb", "prowlarr", "qbittorrent"):
        assert "media-finder-module-sdk" in dependencies[module]
        assert "media-finder-core" not in dependencies[module]
        assert "media-finder-control-contracts" not in dependencies[module]

    assert {
        "media-finder-core",
        "media-finder-control-contracts",
        "media-finder-builtin-ui",
        "media-finder-metadata-manual",
        "media-finder-metadata-tmdb",
        "media-finder-release-prowlarr",
        "media-finder-download-qbittorrent",
    } <= dependencies["server"]


def test_every_workspace_import_has_a_direct_declared_distribution_dependency() -> None:
    import_distributions = {
        "media_finder_server": "media-finder",
        "media_finder_core": "media-finder-core",
        "media_finder_sdk": "media-finder-module-sdk",
        "media_finder_control": "media-finder-control-contracts",
        "media_finder_builtin_ui": "media-finder-builtin-ui",
        "media_finder_metadata_manual": "media-finder-metadata-manual",
        "media_finder_metadata_tmdb": "media-finder-metadata-tmdb",
        "media_finder_release_prowlarr": "media-finder-release-prowlarr",
        "media_finder_download_qbittorrent": "media-finder-download-qbittorrent",
    }
    violations: list[str] = []
    for owner, directory in PACKAGES.items():
        project = _project(directory)
        own_distribution = str(project["name"])
        declared = {
            Requirement(value).name.casefold()
            for value in project.get("dependencies", [])
            if isinstance(value, str)
        }
        for path, line, imported in _imports(directory):
            import_root = imported.partition(".")[0]
            required = import_distributions.get(import_root)
            if required is None or required == own_distribution:
                continue
            if required.casefold() not in declared:
                violations.append(f"{owner}:{path.relative_to(ROOT)}:{line}:{imported}->{required}")

    assert violations == []


def test_every_build_backend_is_exactly_pinned_to_the_uv_lock() -> None:
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    hatchling_version = next(
        str(package["version"]) for package in lock["package"] if package["name"] == "hatchling"
    )
    expected = [f"hatchling=={hatchling_version}"]

    for owner, directory in PACKAGES.items():
        configuration = tomllib.loads((directory / "pyproject.toml").read_text(encoding="utf-8"))
        assert configuration["build-system"] == {
            "requires": expected,
            "build-backend": "hatchling.build",
        }, owner

    root = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert f"hatchling=={hatchling_version}" in root["dependency-groups"]["dev"]


def test_imports_do_not_cross_package_ownership_boundaries() -> None:
    prohibited = {
        "sdk": (
            "alembic",
            "fastapi",
            "httpx",
            "jinja2",
            "media_finder_control",
            "media_finder_core",
            "sqlalchemy",
        ),
        "core": (
            "media_finder_builtin_ui",
            "media_finder_metadata_manual",
            "media_finder_metadata_tmdb",
            "media_finder_release_prowlarr",
            "media_finder_download_qbittorrent",
        ),
        "ui": ("media_finder_core", "media_finder_sdk", "sqlalchemy", "alembic"),
        "manual": ("media_finder_core", "media_finder_control", "sqlalchemy", "fastapi"),
        "tmdb": ("media_finder_core", "media_finder_control", "sqlalchemy", "fastapi"),
        "prowlarr": ("media_finder_core", "media_finder_control", "sqlalchemy", "fastapi"),
        "qbittorrent": ("media_finder_core", "media_finder_control", "sqlalchemy", "fastapi"),
    }
    violations: list[str] = []

    for owner, prefixes in prohibited.items():
        assert (PACKAGES[owner] / "src").is_dir(), f"missing {owner} source package"
        for path, line, imported in _imports(PACKAGES[owner]):
            if any(imported == prefix or imported.startswith(f"{prefix}.") for prefix in prefixes):
                violations.append(f"{path.relative_to(ROOT)}:{line}:{imported}")

    assert violations == []


def test_public_python_distributions_are_typed_and_explicit() -> None:
    expected_import_packages = {
        "server": "media_finder_server",
        "core": "media_finder_core",
        "sdk": "media_finder_sdk",
        "control": "media_finder_control",
        "ui": "media_finder_builtin_ui",
        "manual": "media_finder_metadata_manual",
        "tmdb": "media_finder_metadata_tmdb",
        "prowlarr": "media_finder_release_prowlarr",
        "qbittorrent": "media_finder_download_qbittorrent",
    }

    for distribution, import_name in expected_import_packages.items():
        package = PACKAGES[distribution] / "src" / import_name
        init = package / "__init__.py"
        assert (package / "py.typed").is_file(), f"{distribution} does not publish py.typed"
        assert init.is_file(), f"{distribution} has no public package initializer"
        module = ast.parse(init.read_text(encoding="utf-8"), filename=str(init))
        exported = {
            target.id
            for node in module.body
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name) and target.id == "__all__"
        }
        exported.update(
            node.target.id
            for node in module.body
            if isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "__all__"
        )
        assert exported == {"__all__"}, f"{distribution} does not declare explicit __all__"


def test_only_server_host_contains_concrete_composition() -> None:
    forbidden_outside_host = {
        "FIRST_PARTY_MODULES",
        "media_finder_metadata_manual",
        "media_finder_metadata_tmdb",
        "media_finder_release_prowlarr",
        "media_finder_download_qbittorrent",
    }
    violations: list[str] = []

    production_sources = tuple((ROOT / "packages").glob("**/src/**/*.py"))
    for path in sorted(production_sources):
        content = path.read_text(encoding="utf-8")
        for marker in forbidden_outside_host:
            if marker in content:
                violations.append(f"{path.relative_to(ROOT)}:{marker}")

    assert (PACKAGES["server"] / "src" / "media_finder_server").is_dir()
    assert violations == []


def test_runtime_module_discovery_is_absent() -> None:
    forbidden_calls = {"entry_points", "iter_modules", "walk_packages"}
    violations: list[str] = []

    for directory in PACKAGES.values():
        if not (directory / "src").exists():
            continue
        for path in sorted((directory / "src").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and (
                    (isinstance(node.func, ast.Attribute) and node.func.attr in forbidden_calls)
                    or (isinstance(node.func, ast.Name) and node.func.id in forbidden_calls)
                ):
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")

    assert violations == []


def test_test_runtime_does_not_inject_workspace_source_directories() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert config["tool"]["pytest"]["ini_options"].get("pythonpath", []) == []


def test_builtin_ui_package_owns_fake_only_unit_and_browser_suites() -> None:
    tests = PACKAGES["ui"] / "tests"
    expected = {
        tests / "test_fake_gateway.py",
        tests / "test_html_contract.py",
        tests / "test_browser.py",
    }
    prohibited = (
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
    violations: list[str] = []

    assert all(path.is_file() for path in expected)
    for path in sorted(tests.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            imported: tuple[str, ...] = ()
            if isinstance(node, ast.Import):
                imported = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported = (node.module,)
            for module in imported:
                if any(
                    module == prefix or module.startswith(f"{prefix}.") for prefix in prohibited
                ):
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno}:{module}")

    assert violations == []


def test_first_party_modules_do_not_ship_browser_assets() -> None:
    violations = [
        path.relative_to(ROOT).as_posix()
        for owner in ("manual", "tmdb", "prowlarr", "qbittorrent")
        for path in sorted(PACKAGES[owner].rglob("*"))
        if path.is_file() and path.suffix.casefold() in {".html", ".htm", ".js", ".mjs"}
    ]

    assert violations == []


def test_builtin_ui_does_not_duplicate_concrete_module_translation_catalogs() -> None:
    duplicated = PACKAGES["ui"] / "src" / "media_finder_builtin_ui" / "module_translations"

    assert not tuple(duplicated.rglob("*.json"))
