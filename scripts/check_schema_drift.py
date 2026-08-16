"""Prove a fresh migration head matches the current SQLAlchemy metadata."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from alembic.config import Config

from alembic import command


def main() -> None:
    with TemporaryDirectory(prefix="media-finder-schema-") as directory:
        database = (Path(directory) / "schema.db").as_posix()
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
        command.upgrade(config, "head")
        command.check(config)


if __name__ == "__main__":
    main()
