from logging.config import fileConfig

from media_finder_core.acquisition import persistence as acquisition_persistence
from media_finder_core.catalog import persistence as catalog_persistence
from media_finder_core.platform import persistence as platform_persistence
from media_finder_core.platform.database import Base
from sqlalchemy import engine_from_config, pool

from alembic import context

_CONTEXT_PERSISTENCE = (
    acquisition_persistence,
    catalog_persistence,
    platform_persistence,
)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    try:
        with connectable.connect() as connection:
            context.configure(
                connection=connection, target_metadata=target_metadata, render_as_batch=True
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
