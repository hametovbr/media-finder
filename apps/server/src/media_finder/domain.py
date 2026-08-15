"""Transitional server adapter for the core-owned catalog application service."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from media_finder_core.catalog import CatalogCommands, CatalogIdentity, CatalogQueries
from media_finder_core.catalog.models import RevisionDraft
from media_finder_core.catalog.persistence import SqlAlchemyCatalogRepository
from media_finder_sdk import MediaKind as CoreMediaKind
from media_finder_sdk import NormalizedMetadata as CoreNormalizedMetadata
from media_finder_sdk import ProviderPayload
from pydantic import TypeAdapter, ValidationError
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
    """Compatibility boundary; all catalog state changes delegate to core commands."""

    def __init__(self, session: Session) -> None:
        self.session = session
        repository = SqlAlchemyCatalogRepository(session)
        self._commands = CatalogCommands(repository=repository, clock=utcnow)
        self._queries = CatalogQueries(query_port=repository)

    def get_or_create_item(
        self, provider_key: str, external_id: str, kind: MediaKind | str
    ) -> tuple[MediaItem, bool]:
        resolution = self._commands.get_or_create_item(
            CatalogIdentity(
                provider_id=provider_key,
                external_id=external_id,
                media_kind=CoreMediaKind(str(kind)),
            )
        )
        item = self.session.get(MediaItem, resolution.item.id)
        if item is None:  # pragma: no cover - the repository flushes before returning
            raise RuntimeError("catalog_item_persistence_failed")
        return item, resolution.created

    def create_manual_item(
        self, normalized: NormalizedMetadata, external_id: str | None = None
    ) -> MediaItem:
        identity = external_id or str(uuid4())
        parsed = UUID(identity)
        if parsed.version != 4:
            raise ValueError("Manual external_id must be a UUIDv4")
        identity = str(parsed)
        provider_key = normalized.provenance.provider_key
        item, created = self.get_or_create_item(provider_key, identity, normalized.kind)
        if created:
            provenance = normalized.provenance.model_copy(
                update={"provider_key": provider_key, "external_id": identity}
            )
            self.add_revision(
                item,
                RevisionInput.from_normalized(
                    normalized.model_copy(update={"provenance": provenance})
                ),
            )
        return item

    def add_revision(
        self,
        item: MediaItem,
        revision_input: RevisionInput,
        *,
        commit: bool = True,
    ) -> MetadataRevision:
        normalized = revision_input.normalized
        provenance = normalized.provenance.model_copy(
            update={"provider_key": item.provider_key, "external_id": item.external_id}
        )
        normalized = normalized.model_copy(update={"provenance": provenance})
        overrides = revision_input.overrides or {}
        unknown = set(overrides) - OVERRIDABLE_FIELDS
        if unknown:
            raise ValueError(f"override contains unsupported fields: {sorted(unknown)}")
        try:
            effective = NormalizedMetadata.model_validate(
                normalized.model_dump(mode="json") | overrides
            )
        except ValidationError as error:
            raise ValueError("override does not produce valid normalized metadata") from error
        draft = RevisionDraft(
            raw_payload=(
                ProviderPayload(data=revision_input.raw_payload)
                if revision_input.raw_payload is not None
                else None
            ),
            normalized=_core_metadata(normalized),
            overrides=JSON_OBJECT.dump_python(overrides, mode="json"),
            effective=_core_metadata(effective),
            refresh_after=revision_input.retention.refresh_after,
            expires_at=revision_input.retention.expires_at,
            created_at=revision_input.created_at or utcnow(),
        )
        snapshot = self._commands.append_revision(item.id, draft)
        if commit:
            self.session.commit()
        revision = self.session.get(MetadataRevision, snapshot.id)
        if revision is None:  # pragma: no cover - the repository flushes before returning
            raise RuntimeError("catalog_revision_persistence_failed")
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
        snapshots = self._queries.find_similar(
            title=title,
            year=year,
            excluding_provider_id=excluding_provider,
        )
        return [
            item
            for snapshot in snapshots
            if (item := self.session.get(MediaItem, snapshot.id)) is not None
        ]

    def archive_item(self, item: MediaItem) -> None:
        self._commands.archive_item(item.id)

    def move_item(self, item: MediaItem, collection_id: str | None) -> None:
        self._commands.move_item(item.id, collection_id)
        self.session.commit()


def _core_metadata(metadata: NormalizedMetadata) -> CoreNormalizedMetadata:
    payload = metadata.model_dump(mode="json")
    provenance = payload.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError("metadata_provenance_invalid")
    provenance["provider_id"] = provenance.pop("provider_key")
    return CoreNormalizedMetadata.model_validate(payload)


__all__ = ["CatalogService", "RevisionInput"]
