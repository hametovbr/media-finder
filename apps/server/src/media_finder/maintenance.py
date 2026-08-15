"""Persisted cadence adapter for the core-owned maintenance application service."""

from datetime import datetime, timedelta
from typing import Protocol

from sqlalchemy.orm import Session

from .models import AppSetting


class Coordinator(Protocol):
    def run(self, session: Session, now: datetime) -> None: ...


class MaintenanceRunner:
    """Run generic maintenance at startup and at most once per day."""

    setting_key = "maintenance.last_completed"

    def __init__(self, coordinator: Coordinator) -> None:
        self.coordinator = coordinator

    def run_at_startup(self, session: Session, now: datetime) -> None:
        self.coordinator.run(session, now)
        self._record(session, now)

    def run_if_daily_due(self, session: Session, now: datetime) -> bool:
        setting = session.get(AppSetting, self.setting_key)
        if setting is not None:
            completed = datetime.fromisoformat(setting.value_payload["completed_at"])
            if now - completed < timedelta(days=1):
                return False
        self.coordinator.run(session, now)
        self._record(session, now)
        return True

    def _record(self, session: Session, now: datetime) -> None:
        setting = session.get(AppSetting, self.setting_key)
        if setting is None:
            setting = AppSetting(key=self.setting_key, value_payload={}, secret_reference=False)
            session.add(setting)
        setting.value_payload = {"completed_at": now.isoformat()}
        session.commit()


__all__ = ["MaintenanceRunner"]
