"""Provider-owned retention planning with core-owned atomic persistence."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

from media_finder_sdk import (
    MetadataIdentity,
    MetadataProvider,
    MetadataRetentionPolicy,
    ModuleError,
    ModuleFailureCategory,
    RetentionActionKind,
    RetentionPolicy,
    RetentionSubject,
)

from .commands import CatalogCommands
from .models import MetadataRevisionSnapshot, RevisionDraft
from .ports import CatalogQueryPort, CatalogUnitOfWork
from .validation import (
    revision_draft,
    validate_normalized,
    validate_provider_payload,
    validate_retention_action,
    validate_retention_policy,
)


@dataclass(frozen=True, slots=True)
class RetentionRunSummary:
    examined: int
    refreshed: int
    purged: int
    failed: int


@dataclass(frozen=True, slots=True)
class _PreparedAction:
    revision: MetadataRevisionSnapshot
    kind: RetentionActionKind | None
    refresh_draft: RevisionDraft | None = None
    failure_code: str | None = None


class MetadataRetentionService:
    def __init__(
        self,
        *,
        query_port: CatalogQueryPort,
        unit_of_work: CatalogUnitOfWork,
        policies: Mapping[str, MetadataRetentionPolicy],
        providers: Mapping[str, MetadataProvider],
        clock: Callable[[], datetime],
    ) -> None:
        self._queries = query_port
        self._uow = unit_of_work
        self._policies = policies
        self._providers = providers
        self._clock = clock

    def run(self) -> RetentionRunSummary:
        now = self._clock()
        prepared = tuple(
            self._prepare(revision, now) for revision in self._queries.retention_candidates(now)
        )
        refreshed = purged = failed = 0
        with self._uow.write():
            for action in prepared:
                try:
                    with self._uow.savepoint() as repository:
                        if action.failure_code is not None:
                            repository.record_retention_failure(
                                action.revision.id, action.failure_code, now
                            )
                            failed += 1
                        elif action.kind is RetentionActionKind.PURGE:
                            repository.purge_revision(action.revision.id, now)
                            purged += 1
                        elif action.kind is RetentionActionKind.REFRESH:
                            if (
                                action.refresh_draft is None
                            ):  # pragma: no cover - internal invariant
                                raise RuntimeError("retention_refresh_draft_missing")
                            CatalogCommands(
                                repository=repository, clock=self._clock
                            ).append_revision(
                                action.revision.media_item_id,
                                action.refresh_draft,
                                expected_current_revision_id=action.revision.id,
                            )
                            marker = getattr(repository, "record_retention_refreshed", None)
                            if marker is not None:
                                marker(action.revision.id, now)
                            refreshed += 1
                except Exception:
                    failed += 1
                    with self._uow.savepoint() as repository:
                        repository.record_retention_failure(
                            action.revision.id,
                            "metadata_provider_maintenance_failed",
                            now,
                        )
        return RetentionRunSummary(
            examined=len(prepared),
            refreshed=refreshed,
            purged=purged,
            failed=failed,
        )

    def _prepare(self, revision: MetadataRevisionSnapshot, now: datetime) -> _PreparedAction:
        policy = self._policies.get(revision.identity.provider_id)
        if policy is None:
            return _PreparedAction(
                revision=revision,
                kind=None,
                failure_code="metadata_provider_unavailable",
            )
        identity = MetadataIdentity(
            provider_id=revision.identity.provider_id,
            external_id=revision.identity.external_id,
            media_kind=revision.identity.media_kind,
            locale=revision.locale,
        )
        try:
            action = validate_retention_action(
                policy.plan(
                    RetentionSubject(
                        identity=identity,
                        policy=RetentionPolicy(
                            refresh_after=revision.refresh_after,
                            expires_at=revision.expires_at,
                        ),
                    ),
                    now,
                )
            )
            if (
                action.kind is RetentionActionKind.REFRESH
                and revision.maintenance_status == "refreshed"
            ):
                return _PreparedAction(revision=revision, kind=RetentionActionKind.NONE)
            if action.kind is not RetentionActionKind.REFRESH:
                return _PreparedAction(revision=revision, kind=action.kind)
            provider = self._providers.get(revision.identity.provider_id)
            if provider is None:
                raise ModuleError(
                    category=ModuleFailureCategory.CONFIGURATION,
                    code="metadata_provider_unavailable",
                    safe_details={"operation": "retention"},
                )
            raw_payload = validate_provider_payload(provider.fetch(identity))
            normalized = validate_normalized(
                provider.normalize(raw_payload, identity),
                identity=identity,
            )
            return _PreparedAction(
                revision=revision,
                kind=action.kind,
                refresh_draft=revision_draft(
                    raw_payload=raw_payload,
                    normalized=normalized,
                    retention=validate_retention_policy(policy.retention_for(now)),
                    created_at=now,
                    overrides=revision.overrides,
                ),
            )
        except ModuleError as error:
            return _PreparedAction(
                revision=revision,
                kind=None,
                failure_code=error.code,
            )
        except Exception:
            return _PreparedAction(
                revision=revision,
                kind=None,
                failure_code="metadata_provider_maintenance_failed",
            )


__all__ = ["MetadataRetentionService", "RetentionRunSummary"]
