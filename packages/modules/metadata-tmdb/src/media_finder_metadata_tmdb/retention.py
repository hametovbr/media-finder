"""TMDB-owned calendar retention and export warning policy."""

from __future__ import annotations

from datetime import UTC, datetime
from email.utils import format_datetime

from dateutil.relativedelta import relativedelta
from media_finder_sdk import (
    ExportHeader,
    ExportWarning,
    RetentionAction,
    RetentionActionKind,
    RetentionPolicy,
    RetentionSubject,
)


class TmdbRetentionPolicy:
    def retention_for(self, created_at: datetime) -> RetentionPolicy:
        created = _aware(created_at)
        return RetentionPolicy(
            refresh_after=created + relativedelta(months=5),
            expires_at=created + relativedelta(months=6),
        )

    def plan(self, subject: RetentionSubject, now: datetime) -> RetentionAction:
        current = _aware(now)
        expires = _optional_aware(subject.policy.expires_at)
        refresh = _optional_aware(subject.policy.refresh_after)
        if expires is not None and current >= expires:
            return RetentionAction(kind=RetentionActionKind.PURGE, mandatory=True)
        if refresh is not None and current >= refresh:
            return RetentionAction(kind=RetentionActionKind.REFRESH)
        return RetentionAction(kind=RetentionActionKind.NONE)

    def export_warning(self, policy: RetentionPolicy, now: datetime) -> ExportWarning | None:
        del now
        expires = _optional_aware(policy.expires_at)
        if expires is None:
            return None
        return ExportWarning(
            headers=(
                ExportHeader(
                    name="Warning",
                    value=('299 Media Finder "Provider-derived metadata has a retention deadline"'),
                ),
                ExportHeader(name="Sunset", value=format_datetime(expires, usegmt=True)),
                ExportHeader(
                    name="X-Media-Finder-Metadata-Expires",
                    value=expires.isoformat(),
                ),
            )
        )

    def close(self) -> None:
        return None


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _optional_aware(value: datetime | None) -> datetime | None:
    return None if value is None else _aware(value)


__all__: list[str] = []
