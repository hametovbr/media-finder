import ast
import json
import tomllib
from pathlib import Path

from packaging.version import Version

ROOT = Path(__file__).parents[1]
CONTRACTS_ROOT = ROOT / "packages" / "control-contracts"
UI_ROOT = ROOT / "packages" / "builtin-ui"
WORKSPACE_PROJECTS = (
    ROOT / "apps" / "server" / "pyproject.toml",
    ROOT / "packages" / "builtin-ui" / "pyproject.toml",
    ROOT / "packages" / "control-contracts" / "pyproject.toml",
    ROOT / "packages" / "core" / "pyproject.toml",
    ROOT / "packages" / "module-sdk" / "pyproject.toml",
    ROOT / "packages" / "modules" / "download-qbittorrent" / "pyproject.toml",
    ROOT / "packages" / "modules" / "metadata-manual" / "pyproject.toml",
    ROOT / "packages" / "modules" / "metadata-tmdb" / "pyproject.toml",
    ROOT / "packages" / "modules" / "release-prowlarr" / "pyproject.toml",
)
MODULE_MANIFESTS = tuple(sorted((ROOT / "packages" / "modules").glob("*/src/*/module.toml")))


def _project(path: Path) -> dict[str, object]:
    return tomllib.loads(path.read_text(encoding="utf-8"))["project"]


def test_product_version_is_lockstep_across_workspace_metadata_and_lock() -> None:
    product_version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert str(Version(product_version)) == product_version

    assert {
        str(path.relative_to(ROOT)): _project(path)["version"] for path in WORKSPACE_PROJECTS
    } == {str(path.relative_to(ROOT)): product_version for path in WORKSPACE_PROJECTS}
    assert {
        str(path.relative_to(ROOT)): tomllib.loads(path.read_text(encoding="utf-8"))[
            "module_version"
        ]
        for path in MODULE_MANIFESTS
    } == {str(path.relative_to(ROOT)): product_version for path in MODULE_MANIFESTS}
    assert json.loads((UI_ROOT / "package.json").read_text(encoding="utf-8"))["version"] == (
        product_version
    )

    locked = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    workspace_names = {_project(path)["name"] for path in WORKSPACE_PROJECTS}
    locked_versions = {
        package["name"]: package["version"]
        for package in locked["package"]
        if package["name"] in workspace_names
    }
    assert locked_versions == {name: product_version for name in workspace_names}


def test_workspace_declares_independently_buildable_packages() -> None:
    root_config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert root_config["tool"]["uv"]["workspace"]["members"] == [
        "apps/*",
        "packages/*",
        "packages/modules/*",
    ]
    assert root_config["tool"]["uv"]["sources"] == {
        "media-finder": {"workspace": True},
        "media-finder-core": {"workspace": True},
        "media-finder-module-sdk": {"workspace": True},
        "media-finder-control-contracts": {"workspace": True},
        "media-finder-builtin-ui": {"workspace": True},
        "media-finder-metadata-manual": {"workspace": True},
        "media-finder-metadata-tmdb": {"workspace": True},
        "media-finder-release-prowlarr": {"workspace": True},
        "media-finder-download-qbittorrent": {"workspace": True},
    }

    contracts = _project(CONTRACTS_ROOT / "pyproject.toml")
    ui = _project(UI_ROOT / "pyproject.toml")
    assert contracts["name"] == "media-finder-control-contracts"
    assert contracts["dependencies"] == ["pydantic>=2.11,<3"]
    assert ui["name"] == "media-finder-builtin-ui"
    assert "media-finder-control-contracts" in ui["dependencies"]
    assert "media-finder" not in ui["dependencies"]


def test_root_pytest_discovers_sdk_and_module_suites_but_not_isolated_ui_tests() -> None:
    root_config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert root_config["tool"]["pytest"]["ini_options"]["testpaths"] == [
        "tests",
        "packages/module-sdk/tests",
        "packages/modules/metadata-manual/tests",
        "packages/modules/metadata-tmdb/tests",
        "packages/modules/release-prowlarr/tests",
        "packages/modules/download-qbittorrent/tests",
    ]


def test_builtin_ui_owns_packaged_presentation_resources() -> None:
    package = UI_ROOT / "src" / "media_finder_builtin_ui"
    expected = {
        package / "templates" / "base.html",
        package / "static" / "ui.js",
        package / "locales" / "en" / "LC_MESSAGES" / "messages.mo",
        package / "locales" / "ru" / "LC_MESSAGES" / "messages.mo",
    }

    assert all(path.is_file() for path in expected)


def test_builtin_ui_has_no_backend_or_persistence_imports() -> None:
    package = UI_ROOT / "src" / "media_finder_builtin_ui"
    prohibited = (
        "media_finder",
        "sqlalchemy",
        "alembic",
    )
    violations: list[str] = []

    for path in sorted(package.rglob("*.py")):
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

    assert package.is_dir()
    assert violations == []
