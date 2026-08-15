"""SQLite engine, migrations, and migration-aware readiness."""

from dataclasses import dataclass
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from alembic import command


def create_database(url: str) -> Engine:
    engine = create_engine(url, future=True)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def configure_sqlite(dbapi_connection: object, _: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def _alembic_config(url: str | None = None) -> Config:
    runtime_root = Path.cwd()
    source_root = Path(__file__).resolve().parents[2]
    root = (
        runtime_root
        if (runtime_root / "alembic.ini").is_file() and (runtime_root / "alembic").is_dir()
        else source_root
    )
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    if url:
        config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def migrate_to_head(url: str) -> None:
    command.upgrade(_alembic_config(url), "head")


@dataclass(frozen=True, slots=True)
class MigrationState:
    ready: bool
    current: str | None
    head: str | None


def migration_state(engine: Engine) -> MigrationState:
    config = _alembic_config()
    head = ScriptDirectory.from_config(config).get_current_head()
    with engine.connect() as connection:
        current = MigrationContext.configure(connection).get_current_revision()
    return MigrationState(ready=current == head and head is not None, current=current, head=head)
