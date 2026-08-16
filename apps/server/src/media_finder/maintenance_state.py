"""Temporary SQLAlchemy adapter for core-owned maintenance cadence state."""

from datetime import UTC, datetime

from media_finder_core.platform import SqlAlchemyTransactionOwner
from sqlalchemy.orm import Session, sessionmaker

from .models import AppSetting


class _MaintenanceStateWriter:
    def __init__(self, session: Session) -> None:
        self._session = session

    def record_completed(self, completed_at: datetime) -> None:
        setting = self._session.get(AppSetting, SqlAlchemyMaintenanceState.setting_key)
        if setting is None:
            setting = AppSetting(
                key=SqlAlchemyMaintenanceState.setting_key,
                value_payload={},
                secret_reference=False,
            )
            self._session.add(setting)
        setting.value_payload = {"completed_at": completed_at.isoformat()}


class SqlAlchemyMaintenanceState:
    """Persist the single maintenance checkpoint until the clean schema reset."""

    setting_key = "maintenance.last_completed"

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions
        self._transactions = SqlAlchemyTransactionOwner(
            sessions=sessions,
            resource_factory=_MaintenanceStateWriter,
        )

    def last_completed_at(self) -> datetime | None:
        with self._sessions() as session:
            setting = session.get(AppSetting, self.setting_key)
            if setting is None:
                return None
            completed = datetime.fromisoformat(setting.value_payload["completed_at"])
            return completed if completed.tzinfo is not None else completed.replace(tzinfo=UTC)

    def record_completed(self, completed_at: datetime) -> None:
        with self._transactions.write() as writer:
            writer.record_completed(completed_at)


__all__ = ["SqlAlchemyMaintenanceState"]
