import csv
import io
import json
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier, Event
from uuid import UUID, uuid4

import pytest
from media_finder_core.catalog import ManualCatalogService
from media_finder_core.catalog.persistence import (
    MediaItemRecord as MediaItem,
)
from media_finder_core.catalog.persistence import (
    SqlAlchemyCatalogQueries,
    SqlAlchemyCatalogUnitOfWork,
)
from media_finder_metadata_manual import registration as manual_registration
from media_finder_sdk import (
    EpisodeTableDocument,
    MetadataEditor,
    MetadataImportDocument,
    ModuleError,
    NormalizedMetadata,
    resolve_module_environment,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker


class _BarrierEditor:
    def __init__(self, delegate: MetadataEditor, barrier: Barrier) -> None:
        self._delegate = delegate
        self._barrier = barrier

    def import_document(self, document: MetadataImportDocument):
        result = self._delegate.import_document(document)
        self._barrier.wait(timeout=5)
        return result

    def merge_episode_table(self, current: NormalizedMetadata, document: EpisodeTableDocument):
        return self._delegate.merge_episode_table(current, document)

    def close(self) -> None:
        self._delegate.close()


def _service(database: Session, barrier: Barrier | None = None) -> ManualCatalogService:
    sessions = sessionmaker(bind=database.get_bind(), expire_on_commit=False)
    registration = manual_registration()
    environment = resolve_module_environment(registration.manifest, {})
    assert registration.editor is not None
    editor = registration.editor(environment)
    if barrier is not None:
        editor = _BarrierEditor(editor, barrier)
    return ManualCatalogService(
        query_port=SqlAlchemyCatalogQueries(sessions),
        unit_of_work=SqlAlchemyCatalogUnitOfWork(sessions),
        editor=editor,
        provider_id=registration.manifest.module_id,
        retention_policy=registration.retention(),
        clock=lambda: datetime(2026, 8, 16, tzinfo=UTC),
    )


def _document(value: dict[str, object]) -> MetadataImportDocument:
    return MetadataImportDocument.from_bytes(json.dumps(value).encode("utf-8"))


def movie_document(external_id: str | None = None) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "1",
        "kind": "movie",
        "locale": "en",
        "titles": {"en": "The Snow Queen"},
        "year": 1957,
        "plot": "A restored fairy tale.",
    }
    if external_id is not None:
        value["external_id"] = external_id
    return value


def test_complete_json_import_preserves_or_allocates_uuid4_atomically(
    database: Session,
) -> None:
    service = _service(database)
    supplied = uuid4()
    supplied_item = service.import_item(document=_document(movie_document(str(supplied))))
    assert supplied_item.item.identity.external_id == str(supplied)
    allocated = service.import_item(document=_document(movie_document()))
    assert UUID(allocated.item.identity.external_id).version == 4
    before = database.scalar(select(func.count(MediaItem.id)))
    with pytest.raises(ModuleError):
        service.import_item(document=_document(movie_document("not-a-v4")))
    database.expire_all()
    assert database.scalar(select(func.count(MediaItem.id))) == before


def test_existing_identity_requires_explicit_confirmation(database: Session) -> None:
    service = _service(database)
    identity = str(uuid4())
    original = service.import_item(document=_document(movie_document(identity)))
    with pytest.raises(ValueError, match="duplicate_confirmation_required"):
        service.import_item(document=_document(movie_document(identity)))
    updated = service.import_item(
        document=_document(movie_document(identity) | {"plot": "Updated"}),
        confirm_duplicate=True,
    )
    queries = SqlAlchemyCatalogQueries(sessionmaker(bind=database.get_bind()))
    assert updated.item.id == original.item.id
    assert len(queries.list_revisions(original.item.id)) == 2


def test_episode_csv_import_is_atomic_and_preserves_identity(database: Session) -> None:
    service = _service(database)
    series = service.import_item(
        document=_document(
            {
                "schema_version": "1",
                "kind": "series",
                "locale": "en",
                "titles": {"en": "Local Animation"},
                "seasons": [],
            }
        )
    )
    current_id = series.item.current_revision_id
    assert current_id is not None
    good = io.StringIO(
        "season,episode,title,plot,air_date\n"
        "0,1,Special,Bonus,2024-01-01\n1,1,Pilot,Start,2024-02-01\n"
    )
    updated = service.import_episode_table(
        item_id=series.item.id,
        document=EpisodeTableDocument.from_bytes(good.read().encode()),
        expected_current_revision_id=current_id,
    )
    assert updated.item.identity.external_id == series.item.identity.external_id
    queries = SqlAlchemyCatalogQueries(sessionmaker(bind=database.get_bind()))
    revisions = queries.list_revisions(series.item.id)
    assert revisions[-1].effective is not None
    assert revisions[-1].effective.seasons[0].number == 0
    count = len(revisions)
    bad = io.StringIO("season,episode,title\n1,2,Valid\ninvalid,3,Broken\n")
    with pytest.raises((ModuleError, csv.Error)):
        service.import_episode_table(
            item_id=series.item.id,
            document=EpisodeTableDocument.from_bytes(bad.read().encode()),
            expected_current_revision_id=updated.item.current_revision_id or "",
        )
    assert len(queries.list_revisions(series.item.id)) == count


def _outcomes(
    futures: tuple[Future[object], Future[object]],
) -> tuple[list[object], list[BaseException]]:
    values: list[object] = []
    errors: list[BaseException] = []
    for future in futures:
        try:
            values.append(future.result(timeout=10))
        except BaseException as error:
            errors.append(error)
    return values, errors


def test_concurrent_identity_creation_requires_confirmation_without_sql_errors(
    database: Session,
) -> None:
    identity = str(uuid4())
    barrier = Barrier(2)

    def create() -> object:
        return _service(database, barrier).import_item(document=_document(movie_document(identity)))

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = (pool.submit(create), pool.submit(create))
    values, errors = _outcomes(futures)
    assert len(values) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], ValueError)
    assert str(errors[0]) == "duplicate_confirmation_required"


def test_concurrent_manual_edits_reject_lost_update_without_sql_errors(
    database: Session,
) -> None:
    identity = str(uuid4())
    original = _service(database).import_item(document=_document(movie_document(identity)))
    expected_revision = original.item.current_revision_id
    assert expected_revision is not None
    barrier = Barrier(2)

    def edit(title: str) -> object:
        return _service(database, barrier).edit_item(
            item_id=original.item.id,
            document=_document(movie_document(identity) | {"titles": {"en": title}}),
            expected_current_revision_id=expected_revision,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = (pool.submit(edit, "First"), pool.submit(edit, "Second"))
    values, errors = _outcomes(futures)
    assert len(values) == 1
    assert len(errors) == 1
    assert isinstance(errors[0], ValueError)
    assert str(errors[0]) == "catalog_current_revision_changed"


def test_sqlite_uow_serializes_short_write_sections(database: Session) -> None:
    sessions = sessionmaker(bind=database.get_bind(), expire_on_commit=False)
    first_entered = Event()
    release_first = Event()
    second_entered = Event()

    def first() -> None:
        with SqlAlchemyCatalogUnitOfWork(sessions).write():
            first_entered.set()
            assert release_first.wait(timeout=5)

    def second() -> None:
        assert first_entered.wait(timeout=5)
        with SqlAlchemyCatalogUnitOfWork(sessions).write():
            second_entered.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(first)
        second_future = pool.submit(second)
        assert first_entered.wait(timeout=5)
        assert second_entered.wait(timeout=0.2) is False
        release_first.set()
        first_future.result(timeout=5)
        second_future.result(timeout=5)
    assert second_entered.is_set()
