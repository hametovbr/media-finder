from pathlib import Path

from alembic.config import Config
from sqlalchemy import inspect, text

from media_finder.db import create_database, migrate_to_head, migration_state


def test_fresh_migration_and_sqlite_safety(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'fresh.db'}"
    migrate_to_head(url)
    engine = create_database(url)
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA journal_mode")).scalar_one().lower() == "wal"
        assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        tables = set(inspect(connection).get_table_names())
    assert {
        "collections",
        "media_items",
        "metadata_revisions",
        "acquisitions",
        "download_client_instances",
        "app_settings",
    } <= tables
    assert migration_state(engine).ready is True
    assert isinstance(Config("alembic.ini"), Config)
    engine.dispose()
