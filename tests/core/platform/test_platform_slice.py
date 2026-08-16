"""Target contracts for the core-owned platform boundary."""

from __future__ import annotations

import ast
import importlib
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, BrokenBarrierError
from typing import Any, Protocol, cast

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, insert, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

ROOT = Path(__file__).parents[3]
PLATFORM = ROOT / "packages" / "core" / "src" / "media_finder_core" / "platform"


def _target(module: str, *names: str) -> tuple[Any, ...]:
    qualified = f"media_finder_core.platform.{module}"
    try:
        loaded = importlib.import_module(qualified)
    except ModuleNotFoundError as error:
        pytest.fail(f"platform boundary is missing: {qualified}: {error}")
    missing = [name for name in names if not hasattr(loaded, name)]
    if missing:
        pytest.fail(f"platform boundary is incomplete: {qualified}: {missing}")
    return tuple(getattr(loaded, name) for name in names)


def test_database_builds_safe_sqlite_engine_sessions_and_reports_migration_readiness(
    tmp_path: Path,
) -> None:
    create_database, session_factory, migrate_to_head, migration_state = _target(
        "database",
        "create_database",
        "session_factory",
        "migrate_to_head",
        "migration_state",
    )
    url = f"sqlite:///{tmp_path / 'platform.db'}"
    engine = cast(Engine, create_database(url))
    sessions = cast(sessionmaker[Session], session_factory(engine))

    try:
        assert migration_state(engine).ready is False
        migrate_to_head(url)
        assert migration_state(engine).ready is True
        with engine.connect() as connection:
            assert connection.execute(text("PRAGMA journal_mode")).scalar_one().lower() == "wal"
            assert connection.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
            assert connection.execute(text("PRAGMA busy_timeout")).scalar_one() == 5000
        assert sessions.kw["expire_on_commit"] is False
    finally:
        engine.dispose()


ROWS = Table(
    "platform_transaction_rows",
    MetaData(),
    Column("id", Integer, primary_key=True),
    Column("value", String(40), nullable=False),
)


class _Rows:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, row_id: int, value: str) -> None:
        self._session.execute(insert(ROWS).values(id=row_id, value=value))


def _transaction_owner(
    tmp_path: Path,
) -> tuple[Engine, sessionmaker[Session], Any]:
    create_database, session_factory = _target(
        "database",
        "create_database",
        "session_factory",
    )
    (owner_type,) = _target("transactions", "SqlAlchemyTransactionOwner")
    engine = cast(Engine, create_database(f"sqlite:///{tmp_path / 'transactions.db'}"))
    ROWS.metadata.create_all(engine)
    sessions = cast(sessionmaker[Session], session_factory(engine))
    owner = owner_type(sessions=sessions, resource_factory=_Rows)
    return engine, sessions, owner


def _stored_rows(sessions: sessionmaker[Session]) -> list[tuple[int, str]]:
    with sessions() as session:
        return [(row.id, row.value) for row in session.execute(select(ROWS)).all()]


def test_transaction_owner_commits_once_and_is_reusable_after_outer_rollback(
    tmp_path: Path,
) -> None:
    engine, sessions, owner = _transaction_owner(tmp_path)
    try:
        with pytest.raises(RuntimeError, match="explode"), owner.write() as rows:
            rows.add(1, "rolled-back")
            raise RuntimeError("explode")
        assert _stored_rows(sessions) == []

        with owner.write() as rows:
            rows.add(2, "committed")
            with (
                pytest.raises(RuntimeError, match="transaction_write_already_active"),
                owner.write(),
            ):
                pass
        assert _stored_rows(sessions) == [(2, "committed")]
    finally:
        engine.dispose()


def test_savepoint_rolls_back_only_its_failure_and_requires_an_outer_write(
    tmp_path: Path,
) -> None:
    engine, sessions, owner = _transaction_owner(tmp_path)
    try:
        with (
            pytest.raises(RuntimeError, match="transaction_write_not_active"),
            owner.savepoint(),
        ):
            pass

        with owner.write() as rows:
            rows.add(1, "before")
            with (
                pytest.raises(ValueError, match="bad nested work"),
                owner.savepoint() as nested,
            ):
                assert nested is rows
                nested.add(2, "rolled-back savepoint")
                raise ValueError("bad nested work")
            rows.add(3, "after")

        assert _stored_rows(sessions) == [(1, "before"), (3, "after")]
    finally:
        engine.dispose()


def test_maintenance_state_is_persisted_by_the_platform_context(tmp_path: Path) -> None:
    create_database, session_factory, migrate_to_head = _target(
        "database",
        "create_database",
        "session_factory",
        "migrate_to_head",
    )
    MaintenanceExecutionStateRecord, SqlAlchemyMaintenanceState = _target(
        "persistence",
        "MaintenanceExecutionStateRecord",
        "SqlAlchemyMaintenanceState",
    )
    url = f"sqlite:///{tmp_path / 'maintenance-state.db'}"
    engine = cast(Engine, create_database(url))
    migrate_to_head(url)
    sessions = cast(sessionmaker[Session], session_factory(engine))
    completed_at = datetime(2026, 8, 16, 9, tzinfo=UTC)

    try:
        state = SqlAlchemyMaintenanceState(sessions)
        assert state.last_completed_at() is None
        state.record_completed(completed_at)
        assert state.last_completed_at() == completed_at
        with sessions() as session:
            row = session.get(MaintenanceExecutionStateRecord, "metadata-retention")
            assert row is not None
            assert row.last_completed_at.replace(tzinfo=UTC) == completed_at
    finally:
        engine.dispose()


@dataclass
class _MutableClock:
    current: datetime

    def now(self) -> datetime:
        return self.current


@dataclass
class _MemoryMaintenanceState:
    completed_at: datetime | None = None

    def last_completed_at(self) -> datetime | None:
        return self.completed_at

    def record_completed(self, completed_at: datetime) -> None:
        self.completed_at = completed_at


class _Coordinator:
    def __init__(self) -> None:
        self.calls: list[datetime] = []
        self.failure: Exception | None = None

    def run(self, now: datetime) -> None:
        self.calls.append(now)
        if self.failure is not None:
            raise self.failure


def test_maintenance_runs_at_startup_then_only_when_daily_due() -> None:
    MaintenanceRunner, MaintenanceStatePort = _target(
        "maintenance",
        "MaintenanceRunner",
        "MaintenanceStatePort",
    )
    start = datetime(2026, 8, 16, 9, tzinfo=UTC)
    clock = _MutableClock(start)
    state = _MemoryMaintenanceState(completed_at=start - timedelta(hours=1))
    coordinator = _Coordinator()
    assert isinstance(state, cast(type[Protocol], MaintenanceStatePort))
    runner = MaintenanceRunner(coordinator=coordinator, state=state, clock=clock)

    runner.run_at_startup()
    clock.current = start + timedelta(hours=23, minutes=59)
    assert runner.run_if_daily_due() is False
    clock.current = start + timedelta(days=1)
    assert runner.run_if_daily_due() is True

    assert coordinator.calls == [start, start + timedelta(days=1)]
    assert state.completed_at == start + timedelta(days=1)


def test_failed_maintenance_does_not_advance_durable_cadence_state() -> None:
    (MaintenanceRunner,) = _target("maintenance", "MaintenanceRunner")
    start = datetime(2026, 8, 16, 9, tzinfo=UTC)
    clock = _MutableClock(start)
    state = _MemoryMaintenanceState()
    coordinator = _Coordinator()
    coordinator.failure = RuntimeError("credential=must-not-be-persisted")
    runner = MaintenanceRunner(coordinator=coordinator, state=state, clock=clock)

    with pytest.raises(RuntimeError, match="must-not-be-persisted"):
        runner.run_at_startup()
    assert state.completed_at is None

    coordinator.failure = None
    assert runner.run_if_daily_due() is True
    assert coordinator.calls == [start, start]
    assert state.completed_at == start


def test_ephemeral_cache_is_opaque_lru_bounded_single_use_and_clock_driven() -> None:
    EphemeralCache, EphemeralTokenExpired = _target(
        "cache",
        "EphemeralCache",
        "EphemeralTokenExpired",
    )
    now = datetime(2026, 8, 16, 9, tzinfo=UTC)
    clock = _MutableClock(now)
    cache = EphemeralCache[str](ttl=timedelta(seconds=10), max_entries=2, clock=clock)

    first = cache.put("first private payload")
    second = cache.put("second")
    assert len(first) >= 32
    assert "first" not in first
    assert cache.get(first) == "first private payload"
    third = cache.put("third")

    with pytest.raises(EphemeralTokenExpired):
        cache.get(second)
    assert cache.pop(first) == "first private payload"
    with pytest.raises(EphemeralTokenExpired):
        cache.pop(first)

    clock.current = now + timedelta(seconds=10)
    with pytest.raises(EphemeralTokenExpired):
        cache.get(third)

    with pytest.raises(ValueError, match="cache_bounds_invalid"):
        EphemeralCache(ttl=timedelta(0), max_entries=1, clock=clock)


class _ConcurrentPopClock:
    def __init__(self, current: datetime) -> None:
        self.current = current
        self._barrier = Barrier(2)
        self._armed = False

    def arm(self) -> None:
        self._armed = True

    def now(self) -> datetime:
        if self._armed:
            with suppress(BrokenBarrierError):
                self._barrier.wait(timeout=0.2)
        return self.current


def test_ephemeral_cache_concurrent_pop_has_one_winner_and_stable_losers() -> None:
    EphemeralCache, EphemeralTokenExpired = _target(
        "cache",
        "EphemeralCache",
        "EphemeralTokenExpired",
    )
    clock = _ConcurrentPopClock(datetime(2026, 8, 16, 9, tzinfo=UTC))
    cache = EphemeralCache[str](clock=clock)
    token = cache.put("private payload")
    clock.arm()

    def consume() -> tuple[str, str]:
        try:
            return ("value", cache.pop(token))
        except EphemeralTokenExpired:
            return ("expired", "")
        except Exception as error:  # pragma: no cover - asserted as a regression signal
            return (type(error).__name__, str(error))

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: consume(), range(2)))

    assert sorted(outcomes) == [("expired", ""), ("value", "private payload")]


def test_core_configuration_is_strict_and_never_represents_resolved_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    CoreConfiguration, ConfigurationError = _target(
        "configuration",
        "CoreConfiguration",
        "ConfigurationError",
    )
    environment = {
        "MEDIA_FINDER_DATABASE_URL": "sqlite:////srv/media-finder.db",
        "MEDIA_FINDER_UI_MODE": "disabled",
        "MEDIA_FINDER_SECURE_COOKIE": "false",
        "MEDIA_FINDER_UI_SECRET": "browser-secret-value",
        "MEDIA_FINDER_INTEGRATION_TOKEN": "processor-secret-value",
    }
    config = CoreConfiguration.from_environment(environment)

    assert config.database_url == "sqlite:////srv/media-finder.db"
    assert config.ui_mode == "disabled"
    assert config.secure_cookie is False
    assert config.ui_secret.get_secret_value() == "browser-secret-value"
    assert config.integration_token.get_secret_value() == "processor-secret-value"
    assert "browser-secret-value" not in repr(config)
    assert "processor-secret-value" not in repr(config)

    environment["MEDIA_FINDER_UI_MODE"] = "DISABLED"
    with pytest.raises(ConfigurationError) as invalid:
        CoreConfiguration.from_environment(environment)
    assert invalid.value.code == "core_configuration_invalid"
    assert invalid.value.safe_details == {"variable": "MEDIA_FINDER_UI_MODE"}
    assert "DISABLED" not in str(invalid.value)
    assert "DISABLED" not in repr(invalid.value)

    monkeypatch.setenv("UNRELATED_SECRET", "must-not-be-read")
    minimal = CoreConfiguration.from_environment(
        {
            "MEDIA_FINDER_UI_SECRET": "minimum-browser-secret",
            "MEDIA_FINDER_INTEGRATION_TOKEN": "minimum-processor-secret",
        }
    )
    assert minimal.database_url == "sqlite:////data/media-finder.db"
    assert minimal.ui_mode == "builtin"
    assert minimal.secure_cookie is True
    assert "must-not-be-read" not in repr(minimal)


def test_safe_errors_freeze_allowlisted_details_and_redact_diagnostic_text() -> None:
    SafeError, redact = _target("errors", "SafeError", "redact")
    error = SafeError(
        code="metadata_provider_unavailable",
        safe_details={"missing": ["TMDB_TOKEN"]},
    )

    assert str(error) == "metadata_provider_unavailable"
    assert error.safe_details == {"missing": ("TMDB_TOKEN",)}
    with pytest.raises(TypeError):
        error.safe_details["secret"] = "not allowed"
    with pytest.raises(TypeError, match="safe_error_detail_invalid"):
        SafeError(code="internal_error", safe_details={"exception": object()})

    rendered = redact(
        "failed https://user:pass@example.test/private?api_key=SECRET#fragment SECRET",
        secrets=("SECRET",),
    )
    assert rendered == "failed https://example.test [REDACTED]"


def _imports(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append((node.lineno, node.module))
    return imported


def _matches(module: str, prefixes: tuple[str, ...]) -> bool:
    return any(module == prefix or module.startswith(f"{prefix}.") for prefix in prefixes)


def test_platform_boundary_has_no_delivery_or_concrete_module_dependencies() -> None:
    expected = {
        "database.py",
        "transactions.py",
        "maintenance.py",
        "errors.py",
        "configuration.py",
        "cache.py",
        "clock.py",
        "persistence.py",
    }
    assert expected <= {path.name for path in PLATFORM.glob("*.py")}
    forbidden = (
        "fastapi",
        "starlette",
        "uvicorn",
        "media_finder_server",
        "media_finder_metadata_manual",
        "media_finder_metadata_tmdb",
        "media_finder_release_prowlarr",
        "media_finder_download_qbittorrent",
    )
    framework_free = {"maintenance.py", "errors.py", "configuration.py", "cache.py", "clock.py"}
    violations: list[str] = []

    for path in sorted(PLATFORM.glob("*.py")):
        for line, module in _imports(path):
            if _matches(module, forbidden):
                violations.append(f"{path.name}:{line}:{module}")
            if path.name in framework_free and _matches(module, ("sqlalchemy", "alembic")):
                violations.append(f"{path.name}:{line}:{module}")

    assert violations == []


class _ClockContract(Protocol):
    def now(self) -> datetime: ...


def test_system_clock_is_explicit_and_returns_utc_aware_time() -> None:
    Clock, SystemClock = _target("clock", "Clock", "SystemClock")
    assert isinstance(_MutableClock(datetime(2026, 8, 16, tzinfo=UTC)), Clock)
    clock = cast(_ClockContract, SystemClock())
    before = datetime.now(UTC)
    observed = clock.now()
    after = datetime.now(UTC)
    assert observed.tzinfo is UTC
    assert before <= observed <= after
