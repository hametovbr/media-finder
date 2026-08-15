"""Relational persistence model for the Media Finder control plane."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from media_finder_core.acquisition.persistence import AcquisitionRecord as Acquisition
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
    String,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, Session, mapped_column


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


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    value_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    secret_reference: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


@event.listens_for(Session, "before_flush")
def prevent_download_client_deletion(session: Session, *_: object) -> None:
    if any(isinstance(instance, DownloadClientInstance) for instance in session.deleted):
        raise ValueError("domain records are archive-only and cannot be deleted")


__all__ = [
    "Acquisition",
    "AppSetting",
    "Base",
    "Collection",
    "DownloadClientInstance",
    "MediaItem",
    "MetadataRevision",
]
