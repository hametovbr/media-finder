"""RED contracts for the pre-release, context-owned core schema."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
from typing import Any

import pytest
from media_finder_core.platform.database import create_database, migrate_to_head
from sqlalchemy import inspect

ROOT = Path(__file__).parents[2]
CORE = ROOT / "packages" / "core" / "src" / "media_finder_core"
VERSIONS = ROOT / "alembic" / "versions"

EXPECTED_TABLES = frozenset(
    {
        "collections",
        "media_items",
        "metadata_revisions",
        "acquisitions",
        "maintenance_execution_state",
    }
)
EXPECTED_TABLE_OWNERS = {
    "catalog": frozenset({"collections", "media_items", "metadata_revisions"}),
    "acquisition": frozenset({"acquisitions"}),
    "platform": frozenset({"maintenance_execution_state"}),
}
LEGACY_PERSISTENCE_TOKENS = (
    "app_settings",
    "download_client_instances",
    "download_client_instance_id",
    "config_payload",
    "secret_reference",
    "environment_reference",
    "environment_variable",
)


def _table_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        statement.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        for statement in node.body
        if isinstance(statement, ast.Assign)
        for target in statement.targets
        if isinstance(target, ast.Name)
        and target.id == "__tablename__"
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, str)
    }


def _persistence_sources() -> tuple[Path, ...]:
    return (
        *(CORE.glob("*/persistence.py")),
        *VERSIONS.glob("*.py"),
    )


def _record(module: str, name: str) -> type[Any]:
    try:
        target = importlib.import_module(f"media_finder_core.{module}.persistence")
    except ModuleNotFoundError as error:
        pytest.fail(f"missing {module}-owned persistence adapter: {error}")
    value = getattr(target, name, None)
    if value is None:
        pytest.fail(f"missing {module}-owned record: {name}")
    return value


def test_new_initial_migration_creates_only_the_complete_context_owned_schema(
    tmp_path: Path,
) -> None:
    """A fresh database must contain only the durable records in the approved owner map."""
    engine = create_database(f"sqlite:///{tmp_path / 'clean-schema.db'}")
    try:
        migrate_to_head(str(engine.url))
        assert frozenset(inspect(engine).get_table_names()) - {"alembic_version"} == EXPECTED_TABLES
    finally:
        engine.dispose()


def test_clean_schema_uses_one_pre_release_initial_migration() -> None:
    """A legacy revision chain would silently preserve an unsupported schema history."""
    revisions = sorted(path for path in VERSIONS.glob("*.py") if path.name != "__init__.py")
    assert len(revisions) == 1

    tree = ast.parse(revisions[0].read_text(encoding="utf-8"), filename=str(revisions[0]))
    down_revision = next(
        (
            node.value.value
            for node in tree.body
            if isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "down_revision"
            and isinstance(node.value, ast.Constant)
        ),
        "missing",
    )
    assert down_revision is None


def test_each_context_owns_its_complete_durable_record_set() -> None:
    """Moving a record into the host or another context breaks persistence ownership."""
    actual = {
        context: _table_names(path)
        if (path := CORE / context / "persistence.py").is_file()
        else set()
        for context in EXPECTED_TABLE_OWNERS
    }
    assert actual == EXPECTED_TABLE_OWNERS


def test_acquisition_uses_scalar_catalog_foreign_keys_without_orm_navigation() -> None:
    """Acquisition must retain integrity without making catalog records an ORM API."""
    acquisition = _record("acquisition", "AcquisitionRecord")
    mapper = inspect(acquisition)
    assert set(mapper.relationships) == set()
    assert {
        foreign_key.target_fullname
        for column in mapper.local_table.columns
        for foreign_key in column.foreign_keys
    } == {"media_items.id", "metadata_revisions.id"}


def test_snapshot_records_freeze_revision_and_acquisition_boundary_values() -> None:
    """A stored revision or submitted acquisition must never acquire a new meaning."""
    catalog = importlib.import_module("media_finder_core.catalog.persistence")
    acquisition = importlib.import_module("media_finder_core.acquisition.persistence")

    assert {
        "media_item_id",
        "revision_number",
        "provider_key",
        "external_id",
        "locale",
        "schema_version",
        "provenance_payload",
        "raw_payload",
        "normalized_payload",
        "overrides_payload",
        "effective_payload",
        "refresh_after",
        "expires_at",
        "created_at",
    } <= catalog.IMMUTABLE_REVISION_FIELDS
    assert {
        "media_item_id",
        "metadata_revision_id",
        "idempotency_key",
        "naming_profile",
        "destination",
        "correlation",
        "release_title",
        "indexer",
        "guid",
        "infohash",
        "source_page_url",
        "release_provider_id",
        "release_provider_version",
        "download_client_module_id",
        "download_client_module_version",
        "created_at",
    } <= frozenset(acquisition._IMMUTABLE_FIELDS)


def test_persistence_sources_contain_no_settings_clients_or_integration_configuration() -> None:
    """Integration configuration belongs only to process environment and module manifests."""
    violations = [
        f"{path.relative_to(ROOT)}:{token}"
        for path in _persistence_sources()
        for token in LEGACY_PERSISTENCE_TOKENS
        if token in path.read_text(encoding="utf-8")
    ]
    assert violations == []


def test_acquisition_retains_immutable_module_identity_and_version_snapshots() -> None:
    """Module upgrades must not require reconstructing a historical submission identity."""
    acquisition = _record("acquisition", "AcquisitionRecord")
    assert {
        "release_provider_id",
        "release_provider_version",
        "download_client_module_id",
        "download_client_module_version",
    } <= set(inspect(acquisition).local_table.columns.keys())
