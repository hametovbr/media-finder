"""Provider-agnostic application of module-planned retention actions."""

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from .domain import CatalogService
from .models import AppSetting, MetadataRevision
from .sdk.errors import ModuleError
from .sdk.protocols import MetadataProvider
from .sdk.types import (
    MediaKind,
    RetentionActionKind,
    RetentionExecutionStatus,
    RetentionPolicy,
)


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
                try:
                    action = provider.plan_retention(policy, now)
                except Exception:
                    self._record_failure(revision, now, "metadata_provider_maintenance_failed")
                    continue
                if action.kind is RetentionActionKind.NONE:
                    continue
                if (
                    action.kind is RetentionActionKind.REFRESH
                    and revision.maintenance_status == RetentionExecutionStatus.REFRESHED.value
                ):
                    continue
                revision.maintenance_attempted_at = now
                revision.maintenance_error_code = None
                if action.kind is RetentionActionKind.PURGE:
                    revision.maintenance_status = RetentionExecutionStatus.PURGED.value
                    revision.raw_payload = None
                    revision.normalized_payload = None
                    revision.effective_payload = None
                    revision.expired_at = now
                elif action.kind is RetentionActionKind.REFRESH:
                    media_kind = MediaKind(revision.media_item.kind)
                    try:
                        raw_payload = provider.fetch(
                            media_kind.value, revision.external_id, revision.locale
                        )
                        normalized = provider.normalize(
                            raw_payload,
                            media_kind.value,
                            revision.external_id,
                            revision.locale,
                        )
                        retention = provider.retention_for(now)
                    except ModuleError as error:
                        self._record_failure(revision, now, error.code)
                        continue
                    except Exception:
                        self._record_failure(revision, now, "metadata_provider_maintenance_failed")
                        continue
                    CatalogService(session).add_provider_revision(
                        revision.media_item,
                        raw_payload,
                        normalized,
                        revision.overrides_payload,
                        retention,
                        now,
                    )
                    revision.maintenance_status = RetentionExecutionStatus.REFRESHED.value
            session.commit()
        finally:
            session.info.pop("retention_purge", None)

    @staticmethod
    def _record_failure(revision: MetadataRevision, now: datetime, code: str) -> None:
        revision.maintenance_attempted_at = now
        revision.maintenance_status = RetentionExecutionStatus.FAILED.value
        revision.maintenance_error_code = code


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
