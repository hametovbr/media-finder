"""Subtraction gates for the completed modular server cutover."""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).parents[2]
SERVER_SOURCE = ROOT / "apps" / "server" / "src"
SERVER_PACKAGE = SERVER_SOURCE / "media_finder_server"
CORE_PACKAGE = ROOT / "packages" / "core" / "src" / "media_finder_core"

PYTHON_SCAN_ROOTS = (
    ROOT / "apps",
    ROOT / "packages",
    ROOT / "tests",
)
TEXT_SCAN_ROOTS = (
    ROOT / "apps",
    ROOT / "packages",
    ROOT / "tests",
    ROOT / "docs",
    ROOT / "scripts",
    ROOT / ".github",
)
ROOT_TEXT_FILES = (
    ROOT / "Dockerfile",
    ROOT / "alembic.ini",
    ROOT / "compose.example.yaml",
    ROOT / "pyproject.toml",
)
TEXT_SUFFIXES = frozenset({".md", ".py", ".toml", ".yaml", ".yml"})
CONCRETE_MODULE_PACKAGES = (
    "media_finder_metadata_manual",
    "media_finder_metadata_tmdb",
    "media_finder_release_prowlarr",
    "media_finder_download_qbittorrent",
)
OBSOLETE_SERVER_PATHS = (
    SERVER_PACKAGE / ("integration" + "_runtime.py"),
    SERVER_PACKAGE / ("legacy" + "_registry.py"),
    SERVER_PACKAGE / ("legacy" + "_sdk"),
    SERVER_PACKAGE / "ui.py",
)
OBSOLETE_IDENTIFIERS = frozenset(
    {
        "Default" + "RuntimeFactory",
        "Runtime" + "Resolver",
        "create_" + "legacy_module_registry",
        "create_" + "runtime_factory",
        "create_" + "standalone_processor_app",
        "create_" + "ui_app",
    }
)
OBSOLETE_TEXT_TOKENS = frozenset(
    {
        "legacy" + "_sdk",
        "legacy" + "_registry",
        "Default" + "RuntimeFactory",
        "Runtime" + "Resolver",
    }
)
SHARED_INFRASTRUCTURE_CONSTRUCTORS = frozenset(
    {
        "BackendBrowserSecurity",
        "EphemeralCache",
        "MaintenanceRunner",
        "ModuleRuntime",
        "ReleaseSelectionCache",
        "SqlAlchemyMaintenanceState",
        "create_database",
        "session_factory",
    }
)
INFRASTRUCTURE_CONSTRUCTION_OWNERS = frozenset(
    {
        "apps/server/src/media_finder_server/modules.py",
        "apps/server/src/media_finder_server/runtime.py",
        "packages/core/src/media_finder_core/platform/database.py",
    }
)


def _python_files() -> tuple[Path, ...]:
    return tuple(
        path
        for root in PYTHON_SCAN_ROOTS
        for path in sorted(root.rglob("*.py"))
        if "__pycache__" not in path.parts
    )


def _imports(tree: ast.AST) -> tuple[tuple[int, str], ...]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append((node.lineno, node.module))
    return tuple(found)


def _called_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _defined_and_referenced_identifiers(tree: ast.AST) -> frozenset[str]:
    identifiers: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            identifiers.add(node.id)
        elif isinstance(node, ast.Attribute):
            identifiers.add(node.attr)
        elif isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            identifiers.add(node.name)
    return frozenset(identifiers)


def test_legacy_root_source_package_is_completely_absent() -> None:
    """A second import root would preserve the superseded implementation surface."""

    assert not (SERVER_SOURCE / "media_finder").exists()


def test_repository_python_imports_use_only_the_owned_workspace_packages() -> None:
    """Tests and production code must not keep the removed root importable by accident."""

    old_root = "media" + "_finder"
    violations: list[str] = []
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for line, imported in _imports(tree):
            if imported == old_root or imported.startswith(f"{old_root}."):
                violations.append(f"{path.relative_to(ROOT)}:{line}:{imported}")

    assert violations == []


def test_old_internal_names_are_absent_from_code_documentation_and_configuration() -> None:
    """Compatibility vocabulary would invite contributors to depend on a deleted path."""

    old_root = "media" + "_finder"
    internal_parts = (
        "api",
        "control_adapters",
        "control_api",
        "control_gateway",
        "control_security",
        "domain",
        "integration_runtime",
        "models",
        "modules",
        "runtime",
        "sdk",
        "ui",
    )
    internal_reference = re.compile(rf"\b{old_root}\.(?:{'|'.join(internal_parts)})(?:\b|\.)")
    violations: list[str] = []
    scanned = {
        *(path for path in ROOT_TEXT_FILES if path.is_file()),
        *(
            path
            for root in TEXT_SCAN_ROOTS
            for path in root.rglob("*")
            if path.is_file() and path.suffix.casefold() in TEXT_SUFFIXES
        ),
    }
    for path in sorted(scanned):
        content = path.read_text(encoding="utf-8")
        matched = sorted(token for token in OBSOLETE_TEXT_TOKENS if token in content)
        if matched or internal_reference.search(content):
            violations.append(
                f"{path.relative_to(ROOT)}:{matched or ['removed_root_internal_reference']}"
            )

    assert violations == []


def test_server_contains_no_compatibility_runtime_or_duplicate_composition_adapter() -> None:
    """Only the root runtime may compose shared resources after the typed cutover."""

    path_violations = [
        str(path.relative_to(ROOT)) for path in OBSOLETE_SERVER_PATHS if path.exists()
    ]
    identifier_violations: list[str] = []
    for path in sorted(SERVER_PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        leaked = sorted(_defined_and_referenced_identifiers(tree) & OBSOLETE_IDENTIFIERS)
        if leaked:
            identifier_violations.append(f"{path.relative_to(ROOT)}:{leaked}")

    assert path_violations == []
    assert identifier_violations == []


def test_core_never_imports_a_concrete_integration_package() -> None:
    """Core must depend on the module SDK rather than a first-party implementation."""

    violations: list[str] = []
    for path in sorted(CORE_PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for line, imported in _imports(tree):
            if any(
                imported == package or imported.startswith(f"{package}.")
                for package in CONCRETE_MODULE_PACKAGES
            ):
                violations.append(f"{path.relative_to(ROOT)}:{line}:{imported}")

    assert violations == []


def test_shared_infrastructure_is_created_only_by_server_owners() -> None:
    """Child adapters must receive the root resource graph instead of allocating a second one."""

    violations: list[str] = []
    production_files = tuple((ROOT / "apps").glob("**/src/**/*.py")) + tuple(
        (ROOT / "packages").glob("**/src/**/*.py")
    )
    for path in sorted(production_files):
        relative = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _called_name(node)
            if (
                name in SHARED_INFRASTRUCTURE_CONSTRUCTORS
                and relative not in INFRASTRUCTURE_CONSTRUCTION_OWNERS
            ):
                violations.append(f"{relative}:{node.lineno}:{name}")

    assert violations == []
