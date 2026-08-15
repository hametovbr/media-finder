"""SQLAlchemy persistence owned by the acquisition bounded context."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, TypeVar, cast
from uuid import UUID, uuid4

from media_finder_sdk import SafeReleaseSnapshot
from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    event,
    inspect,
    select,
    text,
    update,
)
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from ..platform.database import Base
from .models import (
    AcquisitionDraft,
    AcquisitionResolution,
    AcquisitionSnapshot,
    AcquisitionStatus,
    ModuleVersionSnapshot,
)

T = TypeVar("T")


class AcquisitionRecord(Base):
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
    destination: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    correlation: Mapped[str] = mapped_column(String(200), nullable=False)
    release_title: Mapped[str | None] = mapped_column(String(1000))
    indexer: Mapped[str | None] = mapped_column(String(300))
    guid: Mapped[str | None] = mapped_column(String(512))
    infohash: Mapped[str | None] = mapped_column(String(100))
    source_page_url: Mapped[str | None] = mapped_column(Text)
    release_provider_id: Mapped[str] = mapped_column(String(100), nullable=False)
    release_provider_version: Mapped[str] = mapped_column(String(100), nullable=False)
    download_client_module_id: Mapped[str] = mapped_column(String(100), nullable=False)
    download_client_module_version: Mapped[str] = mapped_column(String(100), nullable=False)
    external_task_id: Mapped[str | None] = mapped_column(String(500))
    failure_code: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


_IMMUTABLE_FIELDS = (
    "media_item_id",
    "metadata_revision_id",
    "download_client_instance_id",
    "idempotency_key",
    "naming_profile",
    "destination",
    "correlation",
    "release_title",
    "indexer",
    "guid",
    "infohash",
    "source_page_url",
    "release_provider_id",
    "release_provider_version",
    "download_client_module_id",
    "download_client_module_version",
    "created_at",
)


@event.listens_for(Session, "before_flush")
def prevent_acquisition_snapshot_mutation(session: Session, *_: object) -> None:
    if any(isinstance(value, AcquisitionRecord) for value in session.deleted):
        raise ValueError("acquisitions are immutable history and cannot be deleted")
    for value in session.dirty:
        if not isinstance(value, AcquisitionRecord):
            continue
        state = inspect(value)
        if any(state.attrs[name].history.has_changes() for name in _IMMUTABLE_FIELDS):
            raise ValueError("an acquisition's pinned immutable snapshot cannot be changed")


class SqlAlchemyAcquisitionRepository:
    def __init__(
        self,
        session: Session,
        *,
        legacy_download_client_instance_id: str | None = None,
    ) -> None:
        self._session = session
        self._legacy_download_client_instance_id = legacy_download_client_instance_id

    def find_by_idempotency(self, key: str) -> AcquisitionSnapshot | None:
        record = self._session.scalar(
            select(AcquisitionRecord).where(AcquisitionRecord.idempotency_key == key)
        )
        return _snapshot(record) if record is not None else None

    def get(self, acquisition_id: str) -> AcquisitionSnapshot | None:
        identity = _uuid(acquisition_id)
        record = self._session.get(AcquisitionRecord, identity) if identity is not None else None
        return _snapshot(record) if record is not None else None

    def add_pending(self, draft: AcquisitionDraft) -> AcquisitionSnapshot:
        record = AcquisitionRecord(
            id=draft.id,
            media_item_id=draft.media_item_id,
            metadata_revision_id=draft.metadata_revision_id,
            download_client_instance_id=self._legacy_download_client_instance_id,
            idempotency_key=draft.idempotency_key,
            naming_profile=draft.naming_profile,
            status=AcquisitionStatus.PENDING.value,
            destination=draft.destination,
            correlation=draft.correlation,
            release_title=draft.release_snapshot.title,
            indexer=draft.release_snapshot.indexer,
            guid=draft.release_snapshot.guid,
            infohash=(
                draft.release_snapshot.infohash.lower()
                if draft.release_snapshot.infohash is not None
                else None
            ),
            source_page_url=(
                str(draft.release_snapshot.source_page_url)
                if draft.release_snapshot.source_page_url is not None
                else None
            ),
            release_provider_id=draft.release_provider.module_id,
            release_provider_version=draft.release_provider.module_version,
            download_client_module_id=draft.download_client.module_id,
            download_client_module_version=draft.download_client.module_version,
            created_at=draft.created_at,
            updated_at=draft.created_at,
        )
        self._session.add(record)
        self._session.flush()
        return _snapshot(record)

    def create_pending_if_absent(self, draft: AcquisitionDraft) -> AcquisitionResolution:
        existing = self.find_by_idempotency(draft.idempotency_key)
        if existing is not None:
            return AcquisitionResolution(acquisition=existing, created=False)
        try:
            with self._session.begin_nested():
                created = self.add_pending(draft)
        except IntegrityError:
            winner = self.find_by_idempotency(draft.idempotency_key)
            if winner is None:
                raise
            return AcquisitionResolution(acquisition=winner, created=False)
        return AcquisitionResolution(acquisition=created, created=True)

    def transition(
        self,
        acquisition_id: str,
        *,
        expected_status: AcquisitionStatus,
        status: AcquisitionStatus,
        external_task_id: str | None,
        failure_code: str | None,
        updated_at: datetime,
    ) -> AcquisitionSnapshot:
        identity = _required_uuid(acquisition_id)
        result = cast(
            CursorResult[Any],
            self._session.execute(
                update(AcquisitionRecord)
                .where(
                    AcquisitionRecord.id == identity,
                    AcquisitionRecord.status == expected_status.value,
                )
                .values(
                    status=status.value,
                    external_task_id=external_task_id,
                    failure_code=failure_code,
                    updated_at=updated_at,
                )
            ),
        )
        if result.rowcount == 0:
            current = self._session.get(AcquisitionRecord, identity)
            if current is None:
                raise ValueError("acquisition_not_found")
            return _snapshot(current)
        record = self._session.get(AcquisitionRecord, identity)
        if record is None:  # pragma: no cover - guarded by the update predicate
            raise ValueError("acquisition_not_found")
        self._session.refresh(record)
        return _snapshot(record)

    def pending(self) -> tuple[AcquisitionSnapshot, ...]:
        records = self._session.scalars(
            select(AcquisitionRecord)
            .where(AcquisitionRecord.status == AcquisitionStatus.PENDING.value)
            .order_by(AcquisitionRecord.created_at, AcquisitionRecord.id)
        )
        return tuple(_snapshot(record) for record in records)

    def for_media_item(self, media_item_id: str, *, limit: int) -> tuple[AcquisitionSnapshot, ...]:
        records = self._session.scalars(
            select(AcquisitionRecord)
            .where(AcquisitionRecord.media_item_id == media_item_id)
            .order_by(AcquisitionRecord.created_at.desc(), AcquisitionRecord.id.desc())
            .limit(limit)
        )
        return tuple(_snapshot(record) for record in records)


class SqlAlchemyAcquisitionQueries:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        legacy_download_client_instance_id: str | None = None,
    ) -> None:
        self._sessions = sessions
        self._legacy_download_client_instance_id = legacy_download_client_instance_id

    def find_by_idempotency(self, key: str) -> AcquisitionSnapshot | None:
        return self._read(lambda repository: repository.find_by_idempotency(key))

    def get(self, acquisition_id: str) -> AcquisitionSnapshot | None:
        return self._read(lambda repository: repository.get(acquisition_id))

    def pending(self) -> tuple[AcquisitionSnapshot, ...]:
        return self._read(lambda repository: repository.pending())

    def for_media_item(self, media_item_id: str, *, limit: int) -> tuple[AcquisitionSnapshot, ...]:
        return self._read(lambda repository: repository.for_media_item(media_item_id, limit=limit))

    def _read(self, operation: Callable[[SqlAlchemyAcquisitionRepository], T]) -> T:
        with self._sessions() as session:
            return operation(
                SqlAlchemyAcquisitionRepository(
                    session,
                    legacy_download_client_instance_id=self._legacy_download_client_instance_id,
                )
            )


class SqlAlchemyAcquisitionUnitOfWork:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        *,
        legacy_download_client_instance_id: str | None = None,
    ) -> None:
        self._sessions = sessions
        self._legacy_download_client_instance_id = legacy_download_client_instance_id

    @contextmanager
    def write(self) -> Iterator[SqlAlchemyAcquisitionRepository]:
        session = self._sessions()
        try:
            if session.get_bind().dialect.name == "sqlite":
                session.execute(text("BEGIN IMMEDIATE"))
            yield SqlAlchemyAcquisitionRepository(
                session,
                legacy_download_client_instance_id=self._legacy_download_client_instance_id,
            )
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()


def _snapshot(record: AcquisitionRecord) -> AcquisitionSnapshot:
    return AcquisitionSnapshot(
        id=str(record.id),
        media_item_id=record.media_item_id,
        metadata_revision_id=record.metadata_revision_id,
        idempotency_key=record.idempotency_key,
        naming_profile=record.naming_profile,
        status=AcquisitionStatus(record.status),
        destination=record.destination,
        correlation=record.correlation or f"mf-acq-{record.id}",
        release_snapshot=SafeReleaseSnapshot.model_validate(
            {
                "title": record.release_title or "Unknown release",
                "indexer": record.indexer or "Unknown indexer",
                "guid": record.guid,
                "infohash": record.infohash,
                "source_page_url": record.source_page_url,
            }
        ),
        release_provider=ModuleVersionSnapshot(
            module_id=record.release_provider_id,
            module_version=record.release_provider_version,
        ),
        download_client=ModuleVersionSnapshot(
            module_id=record.download_client_module_id,
            module_version=record.download_client_module_version,
        ),
        external_task_id=record.external_task_id,
        failure_code=record.failure_code,
        created_at=_required_utc(record.created_at),
        updated_at=_required_utc(record.updated_at),
    )


def _uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except ValueError:
        return None


def _required_uuid(value: str) -> UUID:
    identity = _uuid(value)
    if identity is None:
        raise ValueError("acquisition_not_found")
    return identity


def _required_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


__all__ = [
    "AcquisitionRecord",
    "SqlAlchemyAcquisitionQueries",
    "SqlAlchemyAcquisitionRepository",
    "SqlAlchemyAcquisitionUnitOfWork",
]
