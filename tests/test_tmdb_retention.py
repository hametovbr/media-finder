from datetime import UTC, datetime

import httpx

from media_finder.domain import CatalogService
from media_finder.maintenance import MaintenanceCoordinator, MaintenanceRunner
from media_finder.modules.registry import FIRST_PARTY_MODULES
from media_finder.sdk.errors import ModuleError
from media_finder.sdk.protocols import MetadataProvider
from media_finder.sdk.types import (
    MediaKind,
    NormalizedMetadata,
    Provenance,
    RetentionAction,
    RetentionActionKind,
    RetentionPolicy,
)


def _tmdb_provider() -> MetadataProvider:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/3/configuration":
            return httpx.Response(200, json={})
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

    registration = FIRST_PARTY_MODULES.metadata_providers["tmdb"]
    return registration.build(
        {"TMDB_TOKEN": "fixture-token"},
        lambda: httpx.Client(transport=httpx.MockTransport(respond)),
        lambda _reference: "fixture-token",
    )


def test_generic_purge_preserves_envelope_overrides_identity_and_acquisition(database) -> None:
    service = CatalogService(database)
    provider = _tmdb_provider()
    item, _ = service.get_or_create_item("tmdb", "129", "movie")
    created = datetime(2024, 1, 1, tzinfo=UTC)
    raw = provider.fetch("movie", "129", "en-US")
    normalized = provider.normalize(raw, "movie", "129", "en-US")
    revision = service.add_provider_revision(
        item,
        {"id": 129, "title": "Spirited Away"},
        normalized,
        {"plot": "Custom"},
        provider.retention_for(created),
        created,
    )
    coordinator = MaintenanceCoordinator({"tmdb": provider})
    coordinator.run(database, datetime(2024, 7, 1, tzinfo=UTC))
    database.refresh(revision)
    assert revision.raw_payload is None
    assert revision.normalized_payload is None
    assert revision.effective_payload is None
    assert revision.overrides_payload == {"plot": "Custom"}
    assert revision.provider_key == "tmdb" and revision.external_id == "129"
    assert revision.expired_at is not None


def test_core_contains_no_provider_policy() -> None:
    from pathlib import Path

    core = Path("src/media_finder/maintenance.py").read_text(encoding="utf-8").lower()
    assert "tmdb" not in core
    assert "month" not in core
    assert "six" not in core


def test_generic_maintenance_runs_at_startup_and_once_daily(database) -> None:
    calls: list[datetime] = []

    class Coordinator:
        def run(self, session, now: datetime) -> None:
            calls.append(now)

    runner = MaintenanceRunner(Coordinator())
    start = datetime(2025, 1, 1, tzinfo=UTC)
    runner.run_at_startup(database, start)
    assert runner.run_if_daily_due(database, datetime(2025, 1, 1, 23, tzinfo=UTC)) is False
    assert runner.run_if_daily_due(database, datetime(2025, 1, 2, tzinfo=UTC)) is True
    assert calls == [start, datetime(2025, 1, 2, tzinfo=UTC)]


def test_generic_refresh_executes_provider_and_persists_new_revision(database) -> None:
    service = CatalogService(database)
    provider = _tmdb_provider()
    item, _ = service.get_or_create_item("tmdb", "129", "movie")
    created = datetime(2024, 1, 1, tzinfo=UTC)
    fetched = provider.fetch("movie", "129", "en-US")
    normalized = provider.normalize(fetched, "movie", "129", "en-US")
    original = service.add_provider_revision(
        item,
        {"id": 129, "title": "Old"},
        normalized,
        {"plot": "User plot"},
        provider.retention_for(created),
        created,
    )
    MaintenanceCoordinator({"tmdb": provider}).run(database, datetime(2024, 6, 1, tzinfo=UTC))
    database.refresh(item)
    database.refresh(original)
    assert original.maintenance_status == "refreshed"
    assert len(item.revisions) == 2
    assert item.revisions[-1].raw_payload["id"] == 129
    assert item.revisions[-1].effective_payload["plot"] == "User plot"
    MaintenanceCoordinator({"tmdb": provider}).run(database, datetime(2024, 6, 2, tzinfo=UTC))
    assert len(item.revisions) == 2

    MaintenanceCoordinator({"tmdb": provider}).run(database, datetime(2024, 7, 1, tzinfo=UTC))
    database.refresh(original)
    assert original.maintenance_status == "purged"
    assert original.expired_at is not None
    assert original.raw_payload is None
    assert len(item.revisions) == 2


class UnexpectedFailureProvider:
    def plan_retention(self, policy: RetentionPolicy, now: datetime) -> RetentionAction:
        return RetentionAction(kind=RetentionActionKind.REFRESH)

    def fetch(self, kind: str, external_id: str, locale: str) -> dict:
        return {"id": external_id}

    def normalize(
        self, payload: dict, kind: str, external_id: str, locale: str
    ) -> NormalizedMetadata:
        raise ValueError("untrusted validation details must not escape")

    def retention_for(self, created_at: datetime) -> RetentionPolicy:
        return RetentionPolicy()


def test_unexpected_revision_failure_is_safe_and_does_not_block_later_purge(database) -> None:
    service = CatalogService(database)
    created = datetime(2024, 1, 1, tzinfo=UTC)
    normalized = NormalizedMetadata(
        kind=MediaKind.MOVIE,
        titles={"en-US": "Fixture"},
        provenance=Provenance(provider_key="unexpected", external_id="failed", locale="en-US"),
    )
    failed_item, _ = service.get_or_create_item("unexpected", "failed", "movie")
    failed = service.add_provider_revision(
        failed_item,
        {"id": "failed"},
        normalized,
        {},
        RetentionPolicy(refresh_after=created),
        created,
    )

    tmdb = _tmdb_provider()
    purge_item, _ = service.get_or_create_item("tmdb", "129", "movie")
    raw = tmdb.fetch("movie", "129", "en-US")
    purge = service.add_provider_revision(
        purge_item,
        raw,
        tmdb.normalize(raw, "movie", "129", "en-US"),
        {},
        tmdb.retention_for(created),
        created,
    )

    MaintenanceCoordinator({"unexpected": UnexpectedFailureProvider(), "tmdb": tmdb}).run(
        database, datetime(2024, 7, 1, tzinfo=UTC)
    )

    database.refresh(failed)
    database.refresh(purge)
    assert failed.maintenance_status == "failed"
    assert failed.maintenance_error_code == "metadata_provider_maintenance_failed"
    assert "untrusted" not in str(failed.maintenance_error_code)
    assert purge.maintenance_status == "purged"


class MismatchedIdentityProvider(UnexpectedFailureProvider):
    def normalize(
        self, payload: dict, kind: str, external_id: str, locale: str
    ) -> NormalizedMetadata:
        return NormalizedMetadata(
            kind=MediaKind(kind),
            titles={locale: "Mismatched"},
            provenance=Provenance(provider_key="mismatch", external_id="different", locale=locale),
        )


def test_revision_savepoint_records_domain_failure_without_erasing_later_purge(database) -> None:
    service = CatalogService(database)
    created = datetime(2024, 1, 1, tzinfo=UTC)
    failed_item, _ = service.get_or_create_item("mismatch", "failed", "movie")
    failed = service.add_provider_revision(
        failed_item,
        {"id": "failed"},
        NormalizedMetadata(
            kind=MediaKind.MOVIE,
            titles={"en-US": "Fixture"},
            provenance=Provenance(provider_key="mismatch", external_id="failed", locale="en-US"),
        ),
        {},
        RetentionPolicy(refresh_after=created),
        created,
    )

    tmdb = _tmdb_provider()
    purge_item, _ = service.get_or_create_item("tmdb", "130", "movie")
    raw = tmdb.fetch("movie", "130", "en-US") | {"id": 130}
    purge = service.add_provider_revision(
        purge_item,
        raw,
        tmdb.normalize(raw, "movie", "130", "en-US"),
        {},
        tmdb.retention_for(created),
        created.replace(day=2),
    )

    MaintenanceCoordinator({"mismatch": MismatchedIdentityProvider(), "tmdb": tmdb}).run(
        database, datetime(2024, 7, 2, tzinfo=UTC)
    )

    database.refresh(failed)
    database.refresh(purge)
    assert failed.maintenance_status == "failed"
    assert failed.maintenance_error_code == "metadata_provider_maintenance_failed"
    assert len(failed_item.revisions) == 1
    assert purge.maintenance_status == "purged"
    assert purge.expired_at is not None


class PublicOnlyFailingRefreshProvider:
    def plan_retention(self, policy: RetentionPolicy, now: datetime) -> RetentionAction:
        return RetentionAction(kind=RetentionActionKind.REFRESH)

    def fetch(self, kind: str, external_id: str, locale: str) -> dict:
        raise ModuleError(
            code="metadata_provider_unavailable",
            message="The metadata provider is temporarily unavailable.",
        )

    def normalize(
        self, payload: dict, kind: str, external_id: str, locale: str
    ) -> NormalizedMetadata:
        raise AssertionError("normalize must not run after a failed fetch")

    def retention_for(self, created_at: datetime) -> RetentionPolicy:
        return RetentionPolicy()


def test_generic_refresh_persists_safe_module_failure_using_public_operations(database) -> None:
    service = CatalogService(database)
    item, _ = service.get_or_create_item("fixture", "failed", "movie")
    created = datetime(2024, 1, 1, tzinfo=UTC)
    normalized = NormalizedMetadata(
        kind=MediaKind.MOVIE,
        titles={"en-US": "Fixture"},
        provenance=Provenance(provider_key="fixture", external_id="failed", locale="en-US"),
    )
    revision = service.add_provider_revision(
        item,
        {"id": "failed"},
        normalized,
        {},
        RetentionPolicy(refresh_after=created),
        created,
    )
    now = datetime(2024, 2, 1, tzinfo=UTC)

    MaintenanceCoordinator({"fixture": PublicOnlyFailingRefreshProvider()}).run(database, now)

    database.refresh(revision)
    assert revision.maintenance_status == "failed"
    assert revision.maintenance_error_code == "metadata_provider_unavailable"
    assert revision.maintenance_attempted_at.replace(tzinfo=UTC) == now
    assert revision.raw_payload == {"id": "failed"}
    assert len(item.revisions) == 1


def test_removed_configuration_still_executes_registered_expiry_purge(database) -> None:
    service = CatalogService(database)
    active = _tmdb_provider()
    item, _ = service.get_or_create_item("tmdb", "129", "movie")
    created = datetime(2024, 1, 1, tzinfo=UTC)
    revision = service.add_provider_revision(
        item,
        {"id": 129},
        active.normalize(active.fetch("movie", "129", "en-US"), "movie", "129", "en-US"),
        {},
        active.retention_for(created),
        created,
    )
    retention_only = FIRST_PARTY_MODULES.metadata_providers["tmdb"].retention_factory()
    MaintenanceCoordinator({"tmdb": retention_only}).run(database, datetime(2024, 7, 1, tzinfo=UTC))
    database.refresh(revision)
    assert revision.expired_at is not None
    assert revision.maintenance_status == "purged"


def test_removed_configuration_records_stable_refresh_failure(database) -> None:
    service = CatalogService(database)
    active = _tmdb_provider()
    item, _ = service.get_or_create_item("tmdb", "129", "movie")
    created = datetime(2024, 1, 1, tzinfo=UTC)
    raw = active.fetch("movie", "129", "en-US")
    revision = service.add_provider_revision(
        item,
        raw,
        active.normalize(raw, "movie", "129", "en-US"),
        {},
        active.retention_for(created),
        created,
    )

    retention_only = FIRST_PARTY_MODULES.metadata_providers["tmdb"].retention_factory()
    MaintenanceCoordinator({"tmdb": retention_only}).run(database, datetime(2024, 6, 1, tzinfo=UTC))

    database.refresh(revision)
    assert revision.maintenance_status == "failed"
    assert revision.maintenance_error_code == "metadata_provider_not_configured"
