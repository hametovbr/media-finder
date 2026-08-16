"""Focused SQLAlchemy catalog fixtures built on the public core application API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from media_finder_core.catalog import CatalogCommands, CatalogIdentity, RevisionDraft
from media_finder_core.catalog.persistence import (
    MediaItemRecord,
    MetadataRevisionRecord,
    SqlAlchemyCatalogRepository,
)
from media_finder_sdk import MediaKind, NormalizedMetadata, ProviderPayload, RetentionPolicy
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class RevisionInput:
    normalized: NormalizedMetadata

    @classmethod
    def from_normalized(cls, normalized: NormalizedMetadata) -> RevisionInput:
        return cls(normalized=normalized)


class CatalogFixture:
    """Seed catalog records through core commands while preserving explicit test commits."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._repository = SqlAlchemyCatalogRepository(session)
        self._commands = CatalogCommands(repository=self._repository, clock=_now)

    def create_manual_item(self, metadata: NormalizedMetadata) -> MediaItemRecord:
        external_id = str(uuid4())
        normalized = _with_identity(metadata, provider_id="manual", external_id=external_id)
        item, _ = self.get_or_create_item("manual", external_id, normalized.kind)
        self.add_revision(item, RevisionInput.from_normalized(normalized))
        return item

    def get_or_create_item(
        self,
        provider_id: str,
        external_id: str,
        kind: MediaKind | str,
    ) -> tuple[MediaItemRecord, bool]:
        identity = CatalogIdentity(
            provider_id=provider_id,
            external_id=external_id,
            media_kind=MediaKind(kind),
        )
        resolved = self._commands.get_or_create_item(identity)
        self._session.commit()
        return self._require_item(resolved.item.id), resolved.created

    def add_revision(
        self,
        item: MediaItemRecord,
        revision: RevisionInput,
    ) -> MetadataRevisionRecord:
        normalized = _with_identity(
            revision.normalized,
            provider_id=item.provider_key,
            external_id=item.external_id,
        )
        created = self._commands.append_revision(
            item.id,
            RevisionDraft(
                raw_payload=None,
                normalized=normalized,
                overrides={},
                effective=normalized,
                refresh_after=None,
                expires_at=None,
                created_at=_now(),
            ),
        )
        self._session.commit()
        self._session.expire_all()
        return self._require_revision(created.id)

    def add_provider_revision(
        self,
        item: MediaItemRecord,
        raw: dict[str, object],
        normalized: NormalizedMetadata,
        overrides: dict[str, object],
        policy: RetentionPolicy,
        created_at: datetime,
    ) -> MetadataRevisionRecord:
        normalized = _with_identity(
            normalized,
            provider_id=item.provider_key,
            external_id=item.external_id,
        )
        effective_payload = normalized.model_dump(mode="python") | overrides
        try:
            effective = TypeAdapter(NormalizedMetadata).validate_python(effective_payload)
        except ValidationError:
            raise ValueError("metadata_override_invalid") from None
        created = self._commands.append_revision(
            item.id,
            RevisionDraft(
                raw_payload=ProviderPayload(data=raw),
                normalized=normalized,
                overrides=overrides,
                effective=effective,
                refresh_after=policy.refresh_after,
                expires_at=policy.expires_at,
                created_at=created_at,
            ),
        )
        self._session.commit()
        self._session.expire_all()
        return self._require_revision(created.id)

    def find_similar(
        self,
        title: str,
        year: int | None,
        *,
        excluding_provider: str,
    ) -> list[MediaItemRecord]:
        snapshots = self._repository.find_similar(
            normalized_title=title,
            year=year,
            excluding_provider_id=excluding_provider,
        )
        return [self._require_item(value.id) for value in snapshots]

    def archive_item(self, item: MediaItemRecord) -> MediaItemRecord:
        self._commands.archive_item(item.id)
        self._session.commit()
        self._session.expire_all()
        return self._require_item(item.id)

    def _require_item(self, item_id: str) -> MediaItemRecord:
        record = self._session.get(MediaItemRecord, item_id)
        if record is None:
            raise AssertionError("catalog_fixture_item_missing")
        return record

    def _require_revision(self, revision_id: str) -> MetadataRevisionRecord:
        record = self._session.get(MetadataRevisionRecord, revision_id)
        if record is None:
            raise AssertionError("catalog_fixture_revision_missing")
        return record


def _with_identity(
    metadata: NormalizedMetadata,
    *,
    provider_id: str,
    external_id: str,
) -> NormalizedMetadata:
    return metadata.model_copy(
        update={
            "provenance": metadata.provenance.model_copy(
                update={"provider_id": provider_id, "external_id": external_id}
            )
        }
    )


def _now() -> datetime:
    return datetime.now(UTC)


__all__ = ["CatalogFixture", "RevisionInput"]
