"""Relational persistence model for the Media Finder control plane."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from media_finder_core.catalog.persistence import (
    CollectionRecord as Collection,
)
from media_finder_core.catalog.persistence import (
    MediaItemRecord as MediaItem,
)
from media_finder_core.catalog.persistence import (
    MetadataRevisionRecord as MetadataRevision,
)
from media_finder_core.platform import Base
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    event,
    inspect,
)
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship


def new_id() -> str:
    return str(uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class DownloadClientInstance(Base):
    __tablename__ = "download_client_instances"
    __table_args__ = (UniqueConstraint("name", name="uq_download_client_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    module_key: Mapped[str] = mapped_column(String(100), nullable=False)
    config_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    system_owned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
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
    destination: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    guid: Mapped[str | None] = mapped_column(String(500))
    infohash: Mapped[str | None] = mapped_column(String(100))
    source_page_url: Mapped[str | None] = mapped_column(Text)
    external_task_id: Mapped[str | None] = mapped_column(String(500))
    failure_code: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    metadata_revision: Mapped[MetadataRevision] = relationship()
    media_item: Mapped[MediaItem] = relationship()
    download_client_instance: Mapped[DownloadClientInstance | None] = relationship()


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    value_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    secret_reference: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


ARCHIVE_ONLY_TYPES = (DownloadClientInstance, Acquisition)


@event.listens_for(Session, "before_flush")
def prevent_revision_envelope_mutation(session: Session, *_: object) -> None:
    if any(isinstance(instance, ARCHIVE_ONLY_TYPES) for instance in session.deleted):
        raise ValueError("domain records are archive-only and cannot be deleted")
    for instance in session.dirty:
        if not isinstance(instance, Acquisition):
            continue
        state = inspect(instance)
        if state.attrs.metadata_revision_id.history.has_changes():
            raise ValueError("an acquisition's pinned metadata revision is immutable")


__all__ = [
    "Acquisition",
    "AppSetting",
    "Base",
    "Collection",
    "DownloadClientInstance",
    "MediaItem",
    "MetadataRevision",
]
