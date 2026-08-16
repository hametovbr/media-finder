"""SQLAlchemy persistence owned by the platform bounded context."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from .database import Base
from .transactions import SqlAlchemyTransactionOwner


class MaintenanceExecutionStateRecord(Base):
    __tablename__ = "maintenance_execution_state"

    task_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    last_completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class _MaintenanceStateWriter:
    def __init__(self, session: Session) -> None:
        self._session = session

    def record_completed(self, completed_at: datetime) -> None:
        record = self._session.get(
            MaintenanceExecutionStateRecord,
            SqlAlchemyMaintenanceState.task_key,
        )
        if record is None:
            record = MaintenanceExecutionStateRecord(
                task_key=SqlAlchemyMaintenanceState.task_key,
                last_completed_at=completed_at,
            )
            self._session.add(record)
        else:
            record.last_completed_at = completed_at


class SqlAlchemyMaintenanceState:
    """Persist the generic maintenance cadence without integration configuration."""

    task_key = "metadata-retention"

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions
        self._transactions = SqlAlchemyTransactionOwner(
            sessions=sessions,
            resource_factory=_MaintenanceStateWriter,
        )

    def last_completed_at(self) -> datetime | None:
        with self._sessions() as session:
            record = session.get(MaintenanceExecutionStateRecord, self.task_key)
            if record is None:
                return None
            value = record.last_completed_at
            return value if value.tzinfo is not None else value.replace(tzinfo=UTC)

    def record_completed(self, completed_at: datetime) -> None:
        with self._transactions.write() as writer:
            writer.record_completed(completed_at)


__all__ = ["MaintenanceExecutionStateRecord", "SqlAlchemyMaintenanceState"]
