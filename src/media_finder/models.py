"""Relational persistence model for the Media Finder control plane."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    event,
    inspect,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class Collection(Base):
    __tablename__ = "collections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    items: Mapped[list["MediaItem"]] = relationship(back_populates="collection")


class MediaItem(Base):
    __tablename__ = "media_items"
    __table_args__ = (
        UniqueConstraint("provider_key", "external_id", name="uq_media_identity"),
        Index("ix_media_similarity", "normalized_title", "year"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    collection: Mapped[Collection | None] = relationship(back_populates="items")
    revisions: Mapped[list["MetadataRevision"]] = relationship(
        back_populates="media_item",
        foreign_keys="MetadataRevision.media_item_id",
        order_by="MetadataRevision.created_at",
    )

    @property
    def current_revision(self) -> "MetadataRevision | None":
        if self.current_revision_id is not None:
            for revision in reversed(self.revisions):
                if revision.id == self.current_revision_id:
                    return revision
        return self.revisions[-1] if self.revisions else None


class MetadataRevision(Base):
    __tablename__ = "metadata_revisions"
    __table_args__ = (
        UniqueConstraint("media_item_id", "revision_number", name="uq_item_revision"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    media_item: Mapped[MediaItem] = relationship(
        back_populates="revisions", foreign_keys=[media_item_id]
    )
    acquisitions: Mapped[list["Acquisition"]] = relationship(back_populates="metadata_revision")


class DownloadClientInstance(Base):
    __tablename__ = "download_client_instances"
    __table_args__ = (UniqueConstraint("name", name="uq_download_client_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    module_key: Mapped[str] = mapped_column(String(100), nullable=False)
    config_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Acquisition(Base):
    __tablename__ = "acquisitions"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_acquisition_idempotency"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    media_item_id: Mapped[str] = mapped_column(
        ForeignKey("media_items.id", ondelete="RESTRICT"), nullable=False
    )
    metadata_revision_id: Mapped[str] = mapped_column(
        ForeignKey("metadata_revisions.id", ondelete="RESTRICT"), nullable=False
    )
    download_client_instance_id: Mapped[str | None] = mapped_column(
        ForeignKey("download_client_instances.id", ondelete="RESTRICT")
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    naming_profile: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    release_title: Mapped[str | None] = mapped_column(String(1000))
    indexer: Mapped[str | None] = mapped_column(String(300))
    guid: Mapped[str | None] = mapped_column(String(500))
    infohash: Mapped[str | None] = mapped_column(String(100))
    source_page_url: Mapped[str | None] = mapped_column(Text)
    failure_code: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    metadata_revision: Mapped[MetadataRevision] = relationship(back_populates="acquisitions")
    media_item: Mapped[MediaItem] = relationship()
    download_client_instance: Mapped[DownloadClientInstance | None] = relationship()


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    value_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    secret_reference: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


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

ARCHIVE_ONLY_TYPES = (Collection, MediaItem, MetadataRevision, DownloadClientInstance, Acquisition)


@event.listens_for(Session, "before_flush")
def prevent_revision_envelope_mutation(session: Session, *_: object) -> None:
    if any(isinstance(instance, ARCHIVE_ONLY_TYPES) for instance in session.deleted):
        raise ValueError("domain records are archive-only and cannot be deleted")
    for instance in session.dirty:
        if not isinstance(instance, MetadataRevision):
            continue
        state = inspect(instance)
        changed = {
            field for field in IMMUTABLE_REVISION_FIELDS if state.attrs[field].history.has_changes()
        }
        retention_fields = {"raw_payload", "normalized_payload", "effective_payload"}
        maintenance_purge = (
            bool(session.info.get("retention_purge")) and changed <= retention_fields
        )
        if changed and not maintenance_purge:
            raise ValueError("metadata revision envelope is immutable")
    for instance in session.dirty:
        if not isinstance(instance, Acquisition):
            continue
        state = inspect(instance)
        if state.attrs.metadata_revision_id.history.has_changes():
            raise ValueError("an acquisition's pinned metadata revision is immutable")
