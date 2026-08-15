"""Transactional catalog operations and immutable revision orchestration."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import MediaItem, MetadataRevision
from .sdk.types import MediaKind, NormalizedMetadata, RetentionPolicy

JSON_OBJECT = TypeAdapter(dict[str, Any])
OVERRIDABLE_FIELDS = {
    "titles",
    "original_title",
    "year",
    "plot",
    "release_date",
    "runtime_minutes",
    "ratings",
    "genres",
    "tags",
    "countries",
    "studios",
    "people",
    "artwork",
    "seasons",
    "completeness",
    "structural_quality",
}


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class RevisionInput:
    normalized: NormalizedMetadata
    raw_payload: dict[str, Any] | None = None
    overrides: dict[str, Any] | None = None
    retention: RetentionPolicy = field(default_factory=RetentionPolicy)
    created_at: datetime | None = None

    @classmethod
    def from_normalized(cls, normalized: NormalizedMetadata) -> "RevisionInput":
        return cls(normalized=normalized)


class CatalogService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_or_create_item(
        self, provider_key: str, external_id: str, kind: MediaKind | str
    ) -> tuple[MediaItem, bool]:
        existing = self.session.scalar(
            select(MediaItem).where(
                MediaItem.provider_key == provider_key, MediaItem.external_id == external_id
            )
        )
        if existing is not None:
            if existing.kind != str(kind):
                raise ValueError("provider_identity_mismatch")
            return existing, False
        item = MediaItem(provider_key=provider_key, external_id=external_id, kind=str(kind))
        self.session.add(item)
        self.session.flush()
        return item, True

    def create_manual_item(
        self, normalized: NormalizedMetadata, external_id: str | None = None
    ) -> MediaItem:
        identity = external_id or str(uuid4())
        parsed = UUID(identity)
        if parsed.version != 4:
            raise ValueError("Manual external_id must be a UUIDv4")
        identity = str(parsed)
        item, created = self.get_or_create_item("manual", identity, normalized.kind)
        if created:
            provenance = normalized.provenance.model_copy(
                update={"provider_key": "manual", "external_id": identity}
            )
            normalized = normalized.model_copy(update={"provenance": provenance})
            self.add_revision(item, RevisionInput.from_normalized(normalized))
        return item

    def add_revision(
        self,
        item: MediaItem,
        revision_input: RevisionInput,
        *,
        commit: bool = True,
    ) -> MetadataRevision:
        normalized = revision_input.normalized
        if normalized.kind.value != item.kind:
            raise ValueError("provider_identity_mismatch")
        payload = normalized.model_dump(mode="json")
        overrides = revision_input.overrides or {}
        unknown = set(overrides) - OVERRIDABLE_FIELDS
        if unknown:
            raise ValueError(f"override contains unsupported fields: {sorted(unknown)}")
        try:
            effective_model = NormalizedMetadata.model_validate(payload | overrides)
        except ValidationError as error:
            raise ValueError("override does not produce valid normalized metadata") from error
        effective = effective_model.model_dump(mode="json")
        serialized_overrides = JSON_OBJECT.dump_python(overrides, mode="json")
        revision = MetadataRevision(
            media_item_id=item.id,
            revision_number=len(item.revisions) + 1,
            provider_key=item.provider_key,
            external_id=item.external_id,
            locale=normalized.provenance.locale,
            schema_version=normalized.schema_version,
            provenance_payload=normalized.provenance.model_dump(mode="json"),
            raw_payload=JSON_OBJECT.dump_python(revision_input.raw_payload, mode="json")
            if revision_input.raw_payload is not None
            else None,
            normalized_payload=payload,
            overrides_payload=serialized_overrides,
            effective_payload=effective,
            refresh_after=revision_input.retention.refresh_after,
            expires_at=revision_input.retention.expires_at,
            created_at=revision_input.created_at or utcnow(),
        )
        item.revisions.append(revision)
        self.session.add(revision)
        self.session.flush()
        item.current_revision_id = revision.id
        item.normalized_title = next(iter(normalized.titles.values())).casefold()
        item.year = normalized.year
        if commit:
            self.session.commit()
        return revision

    def add_provider_revision(
        self,
        item: MediaItem,
        raw_payload: dict[str, Any],
        normalized: NormalizedMetadata,
        overrides: dict[str, Any],
        retention: RetentionPolicy,
        created_at: datetime,
        *,
        commit: bool = True,
    ) -> MetadataRevision:
        if (
            normalized.provenance.provider_key != item.provider_key
            or normalized.provenance.external_id != item.external_id
            or normalized.kind.value != item.kind
        ):
            raise ValueError("normalized provider identity does not match the media item")
        return self.add_revision(
            item,
            RevisionInput(
                normalized=normalized,
                raw_payload=raw_payload,
                overrides=overrides,
                retention=retention,
                created_at=created_at,
            ),
            commit=commit,
        )

    def find_similar(
        self, title: str, year: int | None, *, excluding_provider: str
    ) -> list[MediaItem]:
        return list(
            self.session.scalars(
                select(MediaItem).where(
                    MediaItem.normalized_title == title.casefold(),
                    MediaItem.year == year,
                    MediaItem.provider_key != excluding_provider,
                    MediaItem.archived_at.is_(None),
                )
            )
        )

    def archive_item(self, item: MediaItem) -> None:
        item.archived_at = utcnow()
        self.session.flush()

    def move_item(self, item: MediaItem, collection_id: str | None) -> None:
        item.collection_id = collection_id
        self.session.commit()
