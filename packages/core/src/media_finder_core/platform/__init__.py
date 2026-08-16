"""Core-owned infrastructure primitives and adapters."""

from .cache import EphemeralCache, EphemeralTokenExpired
from .clock import Clock, SystemClock
from .configuration import ConfigurationError, CoreConfiguration
from .database import (
    Base,
    MigrationState,
    UnsupportedMigrationState,
    create_database,
    migrate_to_head,
    migration_state,
    session_factory,
)
from .errors import SafeError, redact, safe_code
from .maintenance import MaintenanceRunner, MaintenanceStatePort
from .persistence import MaintenanceExecutionStateRecord, SqlAlchemyMaintenanceState
from .transactions import SqlAlchemyTransactionOwner, nested_savepoint

__all__ = [
    "Base",
    "Clock",
    "ConfigurationError",
    "CoreConfiguration",
    "EphemeralCache",
    "EphemeralTokenExpired",
    "MaintenanceExecutionStateRecord",
    "MaintenanceRunner",
    "MaintenanceStatePort",
    "MigrationState",
    "SafeError",
    "SqlAlchemyMaintenanceState",
    "SqlAlchemyTransactionOwner",
    "SystemClock",
    "UnsupportedMigrationState",
    "create_database",
    "migrate_to_head",
    "migration_state",
    "nested_savepoint",
    "redact",
    "safe_code",
    "session_factory",
]
