"""Configuration-free Manual metadata retention policy."""

from __future__ import annotations

from datetime import datetime

from media_finder_sdk import (
    ExportWarning,
    RetentionAction,
    RetentionActionKind,
    RetentionPolicy,
    RetentionSubject,
)


class ManualRetentionPolicy:
    def retention_for(self, created_at: datetime) -> RetentionPolicy:
        del created_at
        return RetentionPolicy()

    def plan(self, subject: RetentionSubject, now: datetime) -> RetentionAction:
        del subject, now
        return RetentionAction(kind=RetentionActionKind.NONE)

    def export_warning(self, policy: RetentionPolicy, now: datetime) -> ExportWarning | None:
        del policy, now
        return None

    def close(self) -> None:
        return None


__all__: list[str] = []
