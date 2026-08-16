from datetime import UTC, datetime

import httpx
from media_finder_core.catalog import MetadataCatalogService, MetadataRetentionService
from media_finder_core.catalog.persistence import (
    SqlAlchemyCatalogQueries,
    SqlAlchemyCatalogUnitOfWork,
)
from media_finder_core.platform import MaintenanceRunner
from media_finder_metadata_tmdb import registration as tmdb_registration
from media_finder_sdk import MediaKind, MetadataIdentity, resolve_module_environment
from sqlalchemy.orm import Session, sessionmaker

CREATED = datetime(2024, 1, 1, tzinfo=UTC)


def _registration():
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/3/configuration":
            return httpx.Response(
                200,
                json={"images": {"secure_base_url": "https://image.tmdb.org/t/p/"}},
            )
        return httpx.Response(
            200,
            json={
                "id": 129,
                "title": "Spirited Away",
                "original_title": "Sen to Chihiro no kamikakushi",
                "overview": "A journey.",
                "release_date": "2001-07-20",
                "runtime": 125,
                "genres": [{"name": "Animation"}],
                "production_countries": [{"name": "Japan"}],
                "production_companies": [{"name": "Studio Ghibli"}],
                "vote_average": 8.5,
            },
        )

    return tmdb_registration(
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(respond)),
        clock=lambda: CREATED,
    )


def _seed(database: Session):
    sessions = sessionmaker(bind=database.get_bind(), expire_on_commit=False)
    registration = _registration()
    provider = registration.build(
        resolve_module_environment(registration.manifest, {"TMDB_TOKEN": "fixture-token"})
    )
    provider.validate()
    policy = registration.retention()
    identity = MetadataIdentity(
        provider_id=registration.manifest.module_id,
        external_id="129",
        media_kind=MediaKind.MOVIE,
        locale="en-US",
    )
    outcome = MetadataCatalogService(
        query_port=SqlAlchemyCatalogQueries(sessions),
        unit_of_work=SqlAlchemyCatalogUnitOfWork(sessions),
        clock=lambda: CREATED,
    ).select(identity=identity, provider=provider, retention_policy=policy)
    return sessions, registration.manifest.module_id, provider, policy, outcome


def _retention(
    sessions: sessionmaker[Session],
    *,
    module_id: str,
    policy,
    provider,
    now: datetime,
) -> MetadataRetentionService:
    return MetadataRetentionService(
        query_port=SqlAlchemyCatalogQueries(sessions),
        unit_of_work=SqlAlchemyCatalogUnitOfWork(sessions),
        policies={module_id: policy},
        providers={} if provider is None else {module_id: provider},
        clock=lambda: now,
    )


def test_generic_purge_preserves_revision_envelope_and_identity(database: Session) -> None:
    sessions, module_id, provider, policy, outcome = _seed(database)
    original_id = outcome.item.current_revision_id
    assert original_id is not None
    summary = _retention(
        sessions,
        module_id=module_id,
        policy=policy,
        provider=provider,
        now=datetime(2024, 7, 1, tzinfo=UTC),
    ).run()
    revision = SqlAlchemyCatalogQueries(sessions).get_revision(original_id)
    assert summary.purged == 1
    assert revision is not None
    assert revision.identity.provider_id == module_id
    assert revision.identity.external_id == "129"
    assert revision.raw_payload is None
    assert revision.normalized is None
    assert revision.effective is None
    assert revision.expired_at is not None
    item = SqlAlchemyCatalogQueries(sessions).get_item(outcome.item.id)
    assert item is not None
    assert item.current_revision_id == original_id
    assert item.normalized_title is None
    assert item.year is None


def test_generic_refresh_is_immutable_once_then_original_remains_purgeable(
    database: Session,
) -> None:
    sessions, module_id, provider, policy, outcome = _seed(database)
    original_id = outcome.item.current_revision_id
    assert original_id is not None
    _retention(
        sessions,
        module_id=module_id,
        policy=policy,
        provider=provider,
        now=datetime(2024, 6, 1, tzinfo=UTC),
    ).run()
    revisions = SqlAlchemyCatalogQueries(sessions).list_revisions(outcome.item.id)
    assert len(revisions) == 2
    assert revisions[0].id == original_id
    assert revisions[0].maintenance_status == "refreshed"

    _retention(
        sessions,
        module_id=module_id,
        policy=policy,
        provider=provider,
        now=datetime(2024, 6, 2, tzinfo=UTC),
    ).run()
    assert len(SqlAlchemyCatalogQueries(sessions).list_revisions(outcome.item.id)) == 2

    _retention(
        sessions,
        module_id=module_id,
        policy=policy,
        provider=provider,
        now=datetime(2024, 7, 1, tzinfo=UTC),
    ).run()
    original = SqlAlchemyCatalogQueries(sessions).get_revision(original_id)
    assert original is not None
    assert original.maintenance_status == "purged"


def test_removed_configuration_records_refresh_failure_but_still_allows_purge(
    database: Session,
) -> None:
    sessions, module_id, _provider, policy, outcome = _seed(database)
    revision_id = outcome.item.current_revision_id
    assert revision_id is not None
    _retention(
        sessions,
        module_id=module_id,
        policy=policy,
        provider=None,
        now=datetime(2024, 6, 1, tzinfo=UTC),
    ).run()
    failed = SqlAlchemyCatalogQueries(sessions).get_revision(revision_id)
    assert failed is not None
    assert failed.maintenance_status == "failed"
    assert failed.maintenance_error_code == "metadata_provider_unavailable"

    _retention(
        sessions,
        module_id=module_id,
        policy=policy,
        provider=None,
        now=datetime(2024, 7, 1, tzinfo=UTC),
    ).run()
    purged = SqlAlchemyCatalogQueries(sessions).get_revision(revision_id)
    assert purged is not None
    assert purged.maintenance_status == "purged"


def test_core_contains_no_concrete_provider_policy() -> None:
    from pathlib import Path

    core = Path("packages/core/src/media_finder_core/catalog/retention.py").read_text(
        encoding="utf-8"
    )
    assert all(value not in core.casefold() for value in ("tmdb", "manual", "month", "six"))


def test_generic_maintenance_runs_at_startup_and_once_daily(database: Session) -> None:
    del database
    calls: list[datetime] = []

    class Coordinator:
        def run(self, now: datetime) -> None:
            calls.append(now)

    start = datetime(2025, 1, 1, tzinfo=UTC)

    class Clock:
        current = start

        def now(self) -> datetime:
            return self.current

    class State:
        completed: datetime | None = None

        def last_completed_at(self) -> datetime | None:
            return self.completed

        def record_completed(self, completed_at: datetime) -> None:
            self.completed = completed_at

    clock = Clock()
    runner = MaintenanceRunner(coordinator=Coordinator(), state=State(), clock=clock)
    runner.run_at_startup()
    clock.current = datetime(2025, 1, 1, 23, tzinfo=UTC)
    assert runner.run_if_daily_due() is False
    clock.current = datetime(2025, 1, 2, tzinfo=UTC)
    assert runner.run_if_daily_due() is True
    assert calls == [start, datetime(2025, 1, 2, tzinfo=UTC)]
