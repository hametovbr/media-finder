"""Provider-agnostic application of module-planned retention actions."""

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AppSetting, MetadataRevision
from .sdk.protocols import MetadataProvider
from .sdk.types import RetentionActionKind, RetentionPolicy


class MaintenanceCoordinator:
    def __init__(self, providers: Mapping[str, MetadataProvider]) -> None:
        self.providers = providers

    def run(self, session: Session, now: datetime) -> None:
        revisions = session.scalars(
            select(MetadataRevision).where(MetadataRevision.expired_at.is_(None))
        ).all()
        session.info["retention_purge"] = True
        try:
            for revision in revisions:
                provider = self.providers.get(revision.provider_key)
                if provider is None:
                    continue
                policy = RetentionPolicy(
                    refresh_after=revision.refresh_after,
                    expires_at=revision.expires_at,
                )
                action = provider.plan_retention(policy, now)
                if action.kind is RetentionActionKind.PURGE:
                    revision.raw_payload = None
                    revision.normalized_payload = None
                    revision.effective_payload = None
                    revision.expired_at = now
            session.commit()
        finally:
            session.info.pop("retention_purge", None)


class Coordinator(Protocol):
    def run(self, session: Session, now: datetime) -> None: ...


class MaintenanceRunner:
    """Persist a generic startup and once-per-day maintenance cadence."""

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
