"""Executable boundaries for the target core bounded contexts."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
CORE = ROOT / "packages" / "core" / "src" / "media_finder_core"

CONTEXT_LAYOUT = {
    "catalog": {
        "__init__.py",
        "models.py",
        "commands.py",
        "queries.py",
        "ports.py",
        "persistence.py",
    },
    "acquisition": {
        "__init__.py",
        "models.py",
        "commands.py",
        "queries.py",
        "ports.py",
        "persistence.py",
    },
    "exports": {"__init__.py", "metadata.py", "naming.py", "nfo.py", "ports.py"},
    "module_runtime": {
        "__init__.py",
        "registry.py",
        "configuration.py",
        "lifecycle.py",
        "diagnostics.py",
    },
    "control": {
        "__init__.py",
        "catalog.py",
        "metadata.py",
        "acquisition.py",
        "diagnostics.py",
        "facade.py",
        "security.py",
    },
    "platform": {
        "__init__.py",
        "database.py",
        "transactions.py",
        "maintenance.py",
        "errors.py",
    },
}
CONTEXT_NAMES = frozenset(CONTEXT_LAYOUT)
APPLICATION_FILES = (
    CORE / "catalog" / "commands.py",
    CORE / "catalog" / "queries.py",
    CORE / "acquisition" / "commands.py",
    CORE / "acquisition" / "queries.py",
)
PORT_FILES = (
    CORE / "catalog" / "ports.py",
    CORE / "acquisition" / "ports.py",
    CORE / "exports" / "ports.py",
)
PERSISTENCE_IMPORT_OWNERS = {
    "catalog/persistence.py",
    "acquisition/persistence.py",
    "platform/database.py",
    "platform/transactions.py",
}
CONCRETE_MODULE_PACKAGES = (
    "media_finder_metadata_manual",
    "media_finder_metadata_tmdb",
    "media_finder_release_prowlarr",
    "media_finder_download_qbittorrent",
)
APPLICATION_FORBIDDEN_IMPORTS = (
    "alembic",
    "fastapi",
    "sqlalchemy",
    "media_finder_server",
    *CONCRETE_MODULE_PACKAGES,
)
SESSION_IDENTIFIERS = {"Session", "AsyncSession", "sessionmaker", "scoped_session"}
CONTROL_CONTEXT_IMPORTS = {
    "catalog": {"commands", "queries", "ports"},
    "acquisition": {"commands", "queries", "ports"},
    "exports": {"metadata", "naming", "nfo", "ports"},
    "module_runtime": {"diagnostics"},
    "platform": {"errors"},
}


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports(tree: ast.AST) -> list[tuple[int, str]]:
    imports: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append((node.lineno, node.module))
    return imports


def _matches_prefix(value: str, prefixes: tuple[str, ...]) -> bool:
    return any(value == prefix or value.startswith(f"{prefix}.") for prefix in prefixes)


def _context_import(source_context: str, node: ast.ImportFrom) -> tuple[str, str] | None:
    if node.module is None:
        return None
    if node.module.startswith("media_finder_core."):
        parts = node.module.split(".")[1:]
    elif node.level >= 2:
        parts = node.module.split(".")
    else:
        return None
    if not parts or parts[0] not in CONTEXT_NAMES or parts[0] == source_context:
        return None
    return parts[0], ".".join(parts[1:])


def _absolute_context_import(source_context: str, module: str) -> tuple[str, str] | None:
    if not module.startswith("media_finder_core."):
        return None
    parts = module.split(".")[1:]
    if not parts or parts[0] not in CONTEXT_NAMES or parts[0] == source_context:
        return None
    return parts[0], ".".join(parts[1:])


def _cross_context_allowed(
    source_context: str,
    target_context: str,
    target_module: str,
) -> bool:
    if source_context == "control":
        return target_module in CONTROL_CONTEXT_IMPORTS.get(target_context, set())
    return target_module == "ports"


def _is_protocol(class_node: ast.ClassDef) -> bool:
    return any(
        (isinstance(base, ast.Name) and base.id == "Protocol")
        or (isinstance(base, ast.Attribute) and base.attr == "Protocol")
        for base in class_node.bases
    )


def _is_enum(class_node: ast.ClassDef) -> bool:
    return any(
        (isinstance(base, ast.Name) and base.id.endswith("Enum"))
        or (isinstance(base, ast.Attribute) and base.attr.endswith("Enum"))
        for base in class_node.bases
    )


def _is_frozen_dataclass(class_node: ast.ClassDef) -> bool:
    for decorator in class_node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        name = decorator.func.id if isinstance(decorator.func, ast.Name) else ""
        if name != "dataclass":
            continue
        return any(
            keyword.arg == "frozen"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is True
            for keyword in decorator.keywords
        )
    return False


def _is_frozen_pydantic_model(class_node: ast.ClassDef) -> bool:
    if not any(
        (isinstance(base, ast.Name) and base.id == "BaseModel")
        or (isinstance(base, ast.Attribute) and base.attr == "BaseModel")
        for base in class_node.bases
    ):
        return False
    for statement in class_node.body:
        if not isinstance(statement, ast.Assign | ast.AnnAssign):
            continue
        value = statement.value
        if not isinstance(value, ast.Call):
            continue
        name = value.func.id if isinstance(value.func, ast.Name) else ""
        if name == "ConfigDict" and any(
            keyword.arg == "frozen"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is True
            for keyword in value.keywords
        ):
            return True
    return False


@pytest.mark.parametrize(("context", "required"), CONTEXT_LAYOUT.items())
def test_core_context_has_the_approved_shallow_package(
    context: str,
    required: set[str],
) -> None:
    directory = CORE / context

    assert directory.is_dir(), f"missing core context package: {context}"
    assert required <= {path.name for path in directory.iterdir() if path.is_file()}


def test_command_and_query_services_depend_on_ports_not_frameworks() -> None:
    missing = [str(path.relative_to(ROOT)) for path in APPLICATION_FILES if not path.is_file()]
    assert missing == [], f"missing command/query services: {missing}"

    violations: list[str] = []
    for path in APPLICATION_FILES:
        tree = _tree(path)
        imported = _imports(tree)
        if not any(module == "ports" or module.endswith(".ports") for _, module in imported):
            violations.append(f"{path.relative_to(ROOT)}:application_ports_not_imported")
        for line, module in imported:
            if _matches_prefix(module, APPLICATION_FORBIDDEN_IMPORTS) or module.endswith(
                ".persistence"
            ):
                violations.append(f"{path.relative_to(ROOT)}:{line}:{module}")
        identifiers = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        leaked_sessions = sorted(identifiers & SESSION_IDENTIFIERS)
        if leaked_sessions:
            violations.append(f"{path.relative_to(ROOT)}:direct_session={leaked_sessions!r}")

    assert violations == []


def test_sqlalchemy_and_alembic_imports_are_confined_to_persistence_adapters() -> None:
    violations: list[str] = []

    for path in sorted(CORE.rglob("*.py")):
        relative = path.relative_to(CORE).as_posix()
        for line, module in _imports(_tree(path)):
            if _matches_prefix(module, ("sqlalchemy", "alembic")) and (
                relative not in PERSISTENCE_IMPORT_OWNERS
            ):
                violations.append(f"{relative}:{line}:{module}")

    assert violations == []


def test_cross_context_dependencies_use_only_application_ports() -> None:
    violations: list[str] = []

    for path in sorted(CORE.rglob("*.py")):
        relative = path.relative_to(CORE)
        if len(relative.parts) < 2 or relative.parts[0] not in CONTEXT_NAMES:
            continue
        source_context = relative.parts[0]
        tree = _tree(path)
        for node in ast.walk(tree):
            imported_contexts: list[tuple[str, str]] = []
            if isinstance(node, ast.ImportFrom):
                imported = _context_import(source_context, node)
                if imported is not None:
                    imported_contexts.append(imported)
            elif isinstance(node, ast.Import):
                imported_contexts.extend(
                    imported
                    for alias in node.names
                    if (imported := _absolute_context_import(source_context, alias.name))
                    is not None
                )
            for target_context, target_module in imported_contexts:
                if not _cross_context_allowed(
                    source_context,
                    target_context,
                    target_module,
                ):
                    violations.append(
                        f"{relative.as_posix()}:{node.lineno}:"
                        f"{source_context}->{target_context}.{target_module or '__init__'}"
                    )

    assert violations == []


def test_application_ports_are_framework_free_and_publish_only_immutable_values() -> None:
    missing = [str(path.relative_to(ROOT)) for path in PORT_FILES if not path.is_file()]
    assert missing == [], f"missing application ports: {missing}"

    violations: list[str] = []
    for path in PORT_FILES:
        tree = _tree(path)
        protocols = [
            node for node in tree.body if isinstance(node, ast.ClassDef) and _is_protocol(node)
        ]
        if not protocols:
            violations.append(f"{path.relative_to(ROOT)}:protocol_missing")
        for line, module in _imports(tree):
            if _matches_prefix(module, ("sqlalchemy", "alembic", "fastapi")) or module.endswith(
                ".persistence"
            ):
                violations.append(f"{path.relative_to(ROOT)}:{line}:{module}")
        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or _is_protocol(node) or _is_enum(node):
                continue
            if not (_is_frozen_dataclass(node) or _is_frozen_pydantic_model(node)):
                violations.append(
                    f"{path.relative_to(ROOT)}:{node.lineno}:mutable_boundary_value={node.name}"
                )
        identifiers = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        leaked_sessions = sorted(identifiers & SESSION_IDENTIFIERS)
        if leaked_sessions:
            violations.append(f"{path.relative_to(ROOT)}:direct_session={leaked_sessions!r}")

    assert violations == []


def test_orm_relationships_cannot_target_records_outside_the_owning_context() -> None:
    violations: list[str] = []

    for path in sorted(CORE.glob("*/persistence.py")):
        tree = _tree(path)
        local_records = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
        implicit_targets = {
            id(node.value): ast.unparse(node.annotation)
            for node in ast.walk(tree)
            if isinstance(node, ast.AnnAssign) and isinstance(node.value, ast.Call)
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function_name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else ""
            )
            if function_name != "relationship":
                continue
            if node.args:
                target = node.args[0]
                target_name = (
                    target.value
                    if isinstance(target, ast.Constant) and isinstance(target.value, str)
                    else target.id
                    if isinstance(target, ast.Name)
                    else ""
                )
                owned = target_name in local_records
            else:
                annotation = implicit_targets.get(id(node), "")
                target_name = annotation or "implicit_dynamic"
                owned = any(record in annotation for record in local_records)
            if not owned:
                location = f"{path.relative_to(ROOT)}:{node.lineno}"
                violations.append(f"{location}:relationship={target_name or 'dynamic'}")

    assert violations == []


def test_core_has_no_concrete_release_or_download_client_branch() -> None:
    concrete_ids = {"prowlarr", "qbittorrent"}
    violations: list[str] = []

    for path in sorted(CORE.rglob("*.py")):
        tree = _tree(path)
        for line, module in _imports(tree):
            if _matches_prefix(module, CONCRETE_MODULE_PACKAGES):
                violations.append(f"{path.relative_to(ROOT)}:{line}:{module}")
        for node in ast.walk(tree):
            conditions: tuple[ast.AST, ...] = ()
            if isinstance(node, ast.If | ast.IfExp):
                conditions = (node.test,)
            elif isinstance(node, ast.Match):
                conditions = (
                    node.subject,
                    *(case.pattern for case in node.cases),
                    *(case.guard for case in node.cases if case.guard is not None),
                )
            if not conditions:
                continue
            literals = {
                value.value
                for condition in conditions
                for value in ast.walk(condition)
                if isinstance(value, ast.Constant) and isinstance(value.value, str)
            }
            selected = sorted(literals & concrete_ids)
            if selected:
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}:branch={selected!r}")

    assert violations == []
