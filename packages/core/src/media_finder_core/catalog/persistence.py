"""SQLAlchemy adapter for the catalog context."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from media_finder_sdk import MediaKind, NormalizedMetadata, ProviderPayload
from media_finder_sdk.errors import JsonValue
from pydantic import TypeAdapter
from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    event,
    func,
    inspect,
    or_,
    select,
)
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship, sessionmaker

from ..platform.clock import SystemClock
from ..platform.database import Base
from ..platform.transactions import SqlAlchemyTransactionOwner
from .models import (
    CatalogIdentity,
    CatalogPage,
    CollectionSnapshot,
    MediaItemSnapshot,
    MetadataRevisionSnapshot,
    RevisionDraft,
)

JSON_MAPPING = TypeAdapter(dict[str, JsonValue])
_RETENTION_PURGE_REVISION_KEY = "retention_purge_revision_id"


def _new_id() -> str:
    return str(uuid4())


def _now() -> datetime:
    return SystemClock().now()


class CollectionRecord(Base):
    __tablename__ = "collections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    items: Mapped[list[MediaItemRecord]] = relationship(back_populates="collection")


class MediaItemRecord(Base):
    __tablename__ = "media_items"
    __table_args__ = (
        UniqueConstraint("provider_key", "external_id", name="uq_media_identity"),
        Index("ix_media_similarity", "normalized_title", "year"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    provider_key: Mapped[str] = mapped_column(String(100), nullable=False)
    external_id: Mapped[str] = mapped_column(String(500), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    collection_id: Mapped[str | None] = mapped_column(
        ForeignKey("collections.id", ondelete="RESTRICT")
    )
    normalized_title: Mapped[str | None] = mapped_column(String(500))
    year: Mapped[int | None] = mapped_column(Integer)
    current_revision_id: Mapped[str | None] = mapped_column(String(36))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    collection: Mapped[CollectionRecord | None] = relationship(back_populates="items")
    revisions: Mapped[list[MetadataRevisionRecord]] = relationship(
        back_populates="media_item",
        foreign_keys="MetadataRevisionRecord.media_item_id",
        order_by="MetadataRevisionRecord.revision_number",
    )

    @property
    def current_revision(self) -> MetadataRevisionRecord | None:
        if self.current_revision_id is not None:
            for revision in reversed(self.revisions):
                if revision.id == self.current_revision_id:
                    return revision
        return self.revisions[-1] if self.revisions else None


class MetadataRevisionRecord(Base):
    __tablename__ = "metadata_revisions"
    __table_args__ = (
        UniqueConstraint("media_item_id", "revision_number", name="uq_item_revision"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_new_id)
    media_item_id: Mapped[str] = mapped_column(
        ForeignKey("media_items.id", ondelete="RESTRICT"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_key: Mapped[str] = mapped_column(String(100), nullable=False)
    external_id: Mapped[str] = mapped_column(String(500), nullable=False)
    locale: Mapped[str] = mapped_column(String(50), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)
    provenance_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    normalized_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    overrides_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    effective_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    refresh_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    maintenance_status: Mapped[str | None] = mapped_column(String(30))
    maintenance_error_code: Mapped[str | None] = mapped_column(String(200))
    maintenance_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    media_item: Mapped[MediaItemRecord] = relationship(
        back_populates="revisions", foreign_keys=[media_item_id]
    )


IMMUTABLE_REVISION_FIELDS = {
    "media_item_id",
    "revision_number",
    "provider_key",
    "external_id",
    "locale",
    "schema_version",
    "provenance_payload",
    "raw_payload",
    "normalized_payload",
    "overrides_payload",
    "effective_payload",
    "refresh_after",
    "expires_at",
    "created_at",
}
IMMUTABLE_COLLECTION_FIELDS = {"name", "created_at"}
IMMUTABLE_ITEM_FIELDS = {"provider_key", "external_id", "kind", "created_at"}


@event.listens_for(Session, "before_flush")
def enforce_catalog_immutability(session: Session, *_: object) -> None:
    if any(
        isinstance(instance, CollectionRecord | MediaItemRecord | MetadataRevisionRecord)
        for instance in session.deleted
    ):
        raise ValueError("domain records are archive-only and cannot be deleted")
    for instance in session.dirty:
        if isinstance(instance, CollectionRecord):
            state = inspect(instance)
            if any(
                state.attrs[field].history.has_changes() for field in IMMUTABLE_COLLECTION_FIELDS
            ):
                raise ValueError("catalog collection identity is immutable")
        elif isinstance(instance, MediaItemRecord):
            state = inspect(instance)
            if any(state.attrs[field].history.has_changes() for field in IMMUTABLE_ITEM_FIELDS):
                raise ValueError("catalog media identity is immutable")
    for instance in session.dirty:
        if not isinstance(instance, MetadataRevisionRecord):
            continue
        state = inspect(instance)
        changed = {
            field for field in IMMUTABLE_REVISION_FIELDS if state.attrs[field].history.has_changes()
        }
        retention_fields = {"raw_payload", "normalized_payload", "effective_payload"}
        maintenance_purge = (
            session.info.get(_RETENTION_PURGE_REVISION_KEY) == instance.id
            and changed <= retention_fields
        )
        if changed and not maintenance_purge:
            raise ValueError("metadata revision envelope is immutable")


class SqlAlchemyCatalogRepository:
    """Session-bound adapter that never commits or rolls back its caller's transaction."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add_collection(self, name: str, created_at: datetime) -> CollectionSnapshot:
        record = CollectionRecord(name=name, created_at=created_at)
        self._session.add(record)
        self._session.flush()
        return _collection_snapshot(record)

    def get_collection(self, collection_id: str) -> CollectionSnapshot | None:
        record = self._session.get(CollectionRecord, collection_id)
        return _collection_snapshot(record) if record is not None else None

    def set_collection_archived(
        self, collection_id: str, archived_at: datetime | None
    ) -> CollectionSnapshot:
        record = self._require_collection(collection_id)
        record.archived_at = archived_at
        self._session.flush()
        return _collection_snapshot(record)

    def find_item_by_identity(self, identity: CatalogIdentity) -> MediaItemSnapshot | None:
        record = self._session.scalar(
            select(MediaItemRecord).where(
                MediaItemRecord.provider_key == identity.provider_id,
                MediaItemRecord.external_id == identity.external_id,
            )
        )
        return _item_snapshot(record) if record is not None else None

    def add_item(self, identity: CatalogIdentity, created_at: datetime) -> MediaItemSnapshot:
        record = MediaItemRecord(
            provider_key=identity.provider_id,
            external_id=identity.external_id,
            kind=identity.media_kind.value,
            created_at=created_at,
        )
        self._session.add(record)
        self._session.flush()
        return _item_snapshot(record)

    def get_item(self, item_id: str) -> MediaItemSnapshot | None:
        record = self._session.get(MediaItemRecord, item_id)
        return _item_snapshot(record) if record is not None else None

    def append_revision(self, item_id: str, draft: RevisionDraft) -> MetadataRevisionSnapshot:
        item = self._require_item(item_id)
        next_number = (
            self._session.scalar(
                select(func.max(MetadataRevisionRecord.revision_number)).where(
                    MetadataRevisionRecord.media_item_id == item_id
                )
            )
            or 0
        ) + 1
        normalized_payload = _metadata_to_storage(draft.normalized)
        effective_payload = _metadata_to_storage(draft.effective)
        raw_payload = (
            draft.raw_payload.model_dump(mode="json")["data"]
            if draft.raw_payload is not None
            else None
        )
        provenance_payload = dict(normalized_payload["provenance"])
        overrides_payload = JSON_MAPPING.dump_python(dict(draft.overrides), mode="json")
        revision = MetadataRevisionRecord(
            media_item_id=item_id,
            revision_number=next_number,
            provider_key=item.provider_key,
            external_id=item.external_id,
            locale=draft.normalized.provenance.locale,
            schema_version=draft.normalized.schema_version,
            provenance_payload=provenance_payload,
            raw_payload=raw_payload,
            normalized_payload=normalized_payload,
            overrides_payload=overrides_payload,
            effective_payload=effective_payload,
            refresh_after=draft.refresh_after,
            expires_at=draft.expires_at,
            created_at=draft.created_at,
        )
        self._session.add(revision)
        self._session.flush()
        item.current_revision_id = revision.id
        item.normalized_title = next(iter(draft.effective.titles.values())).casefold()
        item.year = draft.effective.year
        self._session.flush()
        self._session.expire(item, ["revisions"])
        return _revision_snapshot(revision)

    def get_revision(self, revision_id: str) -> MetadataRevisionSnapshot | None:
        record = self._session.get(MetadataRevisionRecord, revision_id)
        return _revision_snapshot(record) if record is not None else None

    def retention_candidates(self, now: datetime) -> tuple[MetadataRevisionSnapshot, ...]:
        del now
        return tuple(
            _revision_snapshot(record)
            for record in self._session.scalars(
                select(MetadataRevisionRecord)
                .where(MetadataRevisionRecord.expired_at.is_(None))
                .order_by(MetadataRevisionRecord.created_at, MetadataRevisionRecord.id)
            )
        )

    def purge_revision(self, revision_id: str, attempted_at: datetime) -> None:
        revision = self._require_revision(revision_id)
        item = self._require_item(revision.media_item_id)
        self._session.info[_RETENTION_PURGE_REVISION_KEY] = revision.id
        try:
            revision.raw_payload = None
            revision.normalized_payload = None
            revision.effective_payload = None
            revision.expired_at = attempted_at
            revision.maintenance_status = "purged"
            revision.maintenance_error_code = None
            revision.maintenance_attempted_at = attempted_at
            if item.current_revision_id == revision.id:
                item.normalized_title = None
                item.year = None
            self._session.flush()
        finally:
            self._session.info.pop(_RETENTION_PURGE_REVISION_KEY, None)

    def record_retention_refreshed(self, revision_id: str, attempted_at: datetime) -> None:
        revision = self._require_revision(revision_id)
        revision.maintenance_status = "refreshed"
        revision.maintenance_error_code = None
        revision.maintenance_attempted_at = attempted_at
        self._session.flush()

    def record_retention_failure(self, revision_id: str, code: str, attempted_at: datetime) -> None:
        revision = self._require_revision(revision_id)
        revision.maintenance_status = "failed"
        revision.maintenance_error_code = code
        revision.maintenance_attempted_at = attempted_at
        self._session.flush()

    def set_item_archived(self, item_id: str, archived_at: datetime | None) -> MediaItemSnapshot:
        record = self._require_item(item_id)
        record.archived_at = archived_at
        self._session.flush()
        return _item_snapshot(record)

    def set_item_collection(self, item_id: str, collection_id: str | None) -> MediaItemSnapshot:
        record = self._require_item(item_id)
        record.collection_id = collection_id
        self._session.flush()
        return _item_snapshot(record)

    def list_revisions(self, item_id: str) -> tuple[MetadataRevisionSnapshot, ...]:
        return tuple(
            _revision_snapshot(record)
            for record in self._session.scalars(
                select(MetadataRevisionRecord)
                .where(MetadataRevisionRecord.media_item_id == item_id)
                .order_by(MetadataRevisionRecord.revision_number, MetadataRevisionRecord.id)
            )
        )

    def page_collections(
        self, *, archived: bool, limit: int, after: tuple[str, str] | None
    ) -> CatalogPage[CollectionSnapshot]:
        query = select(CollectionRecord).where(
            CollectionRecord.archived_at.is_not(None)
            if archived
            else CollectionRecord.archived_at.is_(None)
        )
        if after is not None:
            anchor_name, anchor_id = after
            query = query.where(
                or_(
                    CollectionRecord.name > anchor_name,
                    (CollectionRecord.name == anchor_name) & (CollectionRecord.id > anchor_id),
                )
            )
        records = list(
            self._session.scalars(
                query.order_by(CollectionRecord.name, CollectionRecord.id).limit(limit + 1)
            )
        )
        visible = records[:limit]
        return CatalogPage(
            items=tuple(_collection_snapshot(record) for record in visible),
            next_after=(visible[-1].name, visible[-1].id)
            if len(records) > limit and visible
            else None,
        )

    def page_items(
        self,
        *,
        archived: bool,
        collection_id: str | None,
        uncategorized: bool,
        limit: int,
        after: tuple[str, str] | None,
    ) -> CatalogPage[MediaItemSnapshot]:
        order_title = func.coalesce(MediaItemRecord.normalized_title, "")
        query = select(MediaItemRecord).where(
            MediaItemRecord.archived_at.is_not(None)
            if archived
            else MediaItemRecord.archived_at.is_(None)
        )
        if uncategorized:
            query = query.where(MediaItemRecord.collection_id.is_(None))
        elif collection_id is not None:
            query = query.where(MediaItemRecord.collection_id == collection_id)
        if after is not None:
            anchor_title, anchor_id = after
            query = query.where(
                or_(
                    order_title > anchor_title,
                    (order_title == anchor_title) & (MediaItemRecord.id > anchor_id),
                )
            )
        records = list(
            self._session.scalars(query.order_by(order_title, MediaItemRecord.id).limit(limit + 1))
        )
        visible = records[:limit]
        return CatalogPage(
            items=tuple(_item_snapshot(record) for record in visible),
            next_after=(visible[-1].normalized_title or "", visible[-1].id)
            if len(records) > limit and visible
            else None,
        )

    def find_similar(
        self,
        *,
        normalized_title: str,
        year: int | None,
        excluding_provider_id: str,
    ) -> tuple[MediaItemSnapshot, ...]:
        return tuple(
            _item_snapshot(record)
            for record in self._session.scalars(
                select(MediaItemRecord)
                .where(
                    MediaItemRecord.normalized_title == normalized_title.casefold(),
                    MediaItemRecord.year == year,
                    MediaItemRecord.provider_key != excluding_provider_id,
                    MediaItemRecord.archived_at.is_(None),
                )
                .order_by(MediaItemRecord.normalized_title, MediaItemRecord.id)
            )
        )

    def _require_collection(self, collection_id: str) -> CollectionRecord:
        record = self._session.get(CollectionRecord, collection_id)
        if record is None:
            raise ValueError("collection_not_found")
        return record

    def _require_item(self, item_id: str) -> MediaItemRecord:
        record = self._session.get(MediaItemRecord, item_id)
        if record is None:
            raise ValueError("media_item_not_found")
        return record

    def _require_revision(self, revision_id: str) -> MetadataRevisionRecord:
        record = self._session.get(MetadataRevisionRecord, revision_id)
        if record is None:
            raise ValueError("metadata_revision_not_found")
        return record


class SqlAlchemyCatalogQueries:
    """Short-lived read sessions for catalog application queries."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def get_collection(self, collection_id: str) -> CollectionSnapshot | None:
        with self._sessions() as session:
            return SqlAlchemyCatalogRepository(session).get_collection(collection_id)

    def get_item(self, item_id: str) -> MediaItemSnapshot | None:
        with self._sessions() as session:
            return SqlAlchemyCatalogRepository(session).get_item(item_id)

    def find_item_by_identity(self, identity: CatalogIdentity) -> MediaItemSnapshot | None:
        with self._sessions() as session:
            return SqlAlchemyCatalogRepository(session).find_item_by_identity(identity)

    def list_revisions(self, item_id: str) -> tuple[MetadataRevisionSnapshot, ...]:
        with self._sessions() as session:
            return SqlAlchemyCatalogRepository(session).list_revisions(item_id)

    def get_revision(self, revision_id: str) -> MetadataRevisionSnapshot | None:
        with self._sessions() as session:
            return SqlAlchemyCatalogRepository(session).get_revision(revision_id)

    def retention_candidates(self, now: datetime) -> tuple[MetadataRevisionSnapshot, ...]:
        with self._sessions() as session:
            return SqlAlchemyCatalogRepository(session).retention_candidates(now)

    def page_collections(
        self, *, archived: bool, limit: int, after: tuple[str, str] | None
    ) -> CatalogPage[CollectionSnapshot]:
        with self._sessions() as session:
            return SqlAlchemyCatalogRepository(session).page_collections(
                archived=archived, limit=limit, after=after
            )

    def page_items(
        self,
        *,
        archived: bool,
        collection_id: str | None,
        uncategorized: bool,
        limit: int,
        after: tuple[str, str] | None,
    ) -> CatalogPage[MediaItemSnapshot]:
        with self._sessions() as session:
            return SqlAlchemyCatalogRepository(session).page_items(
                archived=archived,
                collection_id=collection_id,
                uncategorized=uncategorized,
                limit=limit,
                after=after,
            )

    def find_similar(
        self,
        *,
        normalized_title: str,
        year: int | None,
        excluding_provider_id: str,
    ) -> tuple[MediaItemSnapshot, ...]:
        with self._sessions() as session:
            return SqlAlchemyCatalogRepository(session).find_similar(
                normalized_title=normalized_title,
                year=year,
                excluding_provider_id=excluding_provider_id,
            )

    def has_pinned_revision(self, media_item_id: str, metadata_revision_id: str) -> bool:
        with self._sessions() as session:
            revision = SqlAlchemyCatalogRepository(session).get_revision(metadata_revision_id)
            return revision is not None and revision.media_item_id == media_item_id


class SqlAlchemyCatalogUnitOfWork:
    """Own one write transaction and expose explicit nested savepoints."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._transactions = SqlAlchemyTransactionOwner(
            sessions=sessions,
            resource_factory=SqlAlchemyCatalogRepository,
        )

    @contextmanager
    def write(self) -> Iterator[SqlAlchemyCatalogRepository]:
        with self._transactions.write() as repository:
            yield repository

    @contextmanager
    def savepoint(self) -> Iterator[SqlAlchemyCatalogRepository]:
        with self._transactions.savepoint() as repository:
            yield repository


def _metadata_to_storage(metadata: NormalizedMetadata) -> dict[str, Any]:
    payload = metadata.model_dump(mode="json")
    provenance = payload.get("provenance")
    if isinstance(provenance, dict):
        provenance["provider_key"] = provenance.pop("provider_id")
    return payload


def _metadata_from_storage(payload: dict[str, Any] | None) -> NormalizedMetadata | None:
    if payload is None:
        return None
    copied = dict(payload)
    provenance_value = copied.get("provenance")
    if isinstance(provenance_value, dict):
        provenance = dict(provenance_value)
        if "provider_id" not in provenance and "provider_key" in provenance:
            provenance["provider_id"] = provenance.pop("provider_key")
        copied["provenance"] = provenance
    return NormalizedMetadata.model_validate(copied)


def _collection_snapshot(record: CollectionRecord) -> CollectionSnapshot:
    return CollectionSnapshot(
        id=record.id,
        name=record.name,
        archived_at=_utc(record.archived_at),
        created_at=_required_utc(record.created_at),
    )


def _item_snapshot(record: MediaItemRecord) -> MediaItemSnapshot:
    return MediaItemSnapshot(
        id=record.id,
        identity=CatalogIdentity(
            provider_id=record.provider_key,
            external_id=record.external_id,
            media_kind=MediaKind(record.kind),
        ),
        collection_id=record.collection_id,
        normalized_title=record.normalized_title,
        year=record.year,
        current_revision_id=record.current_revision_id,
        archived_at=_utc(record.archived_at),
        created_at=_required_utc(record.created_at),
    )


def _revision_snapshot(record: MetadataRevisionRecord) -> MetadataRevisionSnapshot:
    raw = ProviderPayload(data=record.raw_payload) if record.raw_payload is not None else None
    return MetadataRevisionSnapshot(
        id=record.id,
        media_item_id=record.media_item_id,
        revision_number=record.revision_number,
        identity=CatalogIdentity(
            provider_id=record.provider_key,
            external_id=record.external_id,
            media_kind=MediaKind(record.media_item.kind),
        ),
        locale=record.locale,
        schema_version=record.schema_version,
        raw_payload=raw,
        normalized=_metadata_from_storage(record.normalized_payload),
        overrides=record.overrides_payload,
        effective=_metadata_from_storage(record.effective_payload),
        refresh_after=_utc(record.refresh_after),
        expires_at=_utc(record.expires_at),
        expired_at=_utc(record.expired_at),
        maintenance_status=record.maintenance_status,
        maintenance_error_code=record.maintenance_error_code,
        maintenance_attempted_at=_utc(record.maintenance_attempted_at),
        created_at=_required_utc(record.created_at),
    )


def _utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def _required_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


__all__ = [
    "CollectionRecord",
    "MediaItemRecord",
    "MetadataRevisionRecord",
    "SqlAlchemyCatalogQueries",
    "SqlAlchemyCatalogRepository",
    "SqlAlchemyCatalogUnitOfWork",
]
