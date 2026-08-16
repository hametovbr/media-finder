from pathlib import Path

import pytest
from alembic.config import Config
from media_finder_core.platform.database import (
    _alembic_config,
    create_database,
    migrate_to_head,
    migration_state,
)
from sqlalchemy import inspect, text


def test_fresh_migration_and_sqlite_safety(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'fresh.db'}"
    migrate_to_head(url)
    engine = create_database(url)
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA journal_mode")).scalar_one().lower() == "wal"
        assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        tables = set(inspect(connection).get_table_names())
    assert tables == {
        "alembic_version",
        "collections",
        "media_items",
        "metadata_revisions",
        "acquisitions",
        "maintenance_execution_state",
    }
    assert migration_state(engine).ready is True
    assert isinstance(Config("alembic.ini"), Config)
    engine.dispose()


def test_old_pre_release_revision_requires_disposable_data_reset(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    engine = create_database(url)
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(64))"))
            connection.execute(
                text(
                    "INSERT INTO alembic_version (version_num) "
                    "VALUES ('0004_acquisition_module_snapshots')"
                )
            )

        with pytest.raises(
            RuntimeError,
            match="unsupported_database_revision_recreate_disposable_data",
        ) as failure:
            migrate_to_head(url)

        assert str(failure.value) == "unsupported_database_revision_recreate_disposable_data"
        assert "0004_acquisition_module_snapshots" not in str(failure.value)
    finally:
        engine.dispose()


def test_alembic_config_uses_valid_runtime_working_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "alembic").mkdir()
    (tmp_path / "alembic.ini").write_text(
        "[alembic]\nscript_location = alembic\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    config = _alembic_config("sqlite:///runtime.db")

    assert Path(config.config_file_name or "") == tmp_path / "alembic.ini"
    assert config.get_main_option("script_location") == str(tmp_path / "alembic")
