from datetime import UTC, datetime

import pytest

from media_finder.domain import CatalogService
from media_finder.maintenance import MaintenanceCoordinator, MaintenanceRunner
from media_finder.modules.tmdb import TmdbConfig, TmdbProvider
from media_finder.sdk.errors import ModuleError
from media_finder.sdk.types import RetentionActionKind


class FixtureTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get_json(self, path: str, params: dict[str, str]) -> dict:
        self.calls.append((path, params))
        if path == "/search/movie":
            return {
                "results": [
                    {
                        "id": 129,
                        "title": "Spirited Away",
                        "release_date": "2001-07-20",
                        "overview": "A journey.",
                    }
                ]
            }
        if path == "/search/tv":
            return {
                "results": [
                    {
                        "id": 200,
                        "name": "Fixture Series",
                        "first_air_date": "2020-01-01",
                        "overview": "Series result",
                    }
                ]
            }
        return {
            "id": 129,
            "title": "Spirited Away",
            "original_title": "千と千尋の神隠し",
            "overview": "A journey.",
            "release_date": "2001-07-20",
            "runtime": 125,
            "genres": [{"name": "Animation"}],
            "production_countries": [{"name": "Japan"}],
            "production_companies": [{"name": "Studio Ghibli"}],
            "vote_average": 8.5,
        }


class SeriesTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get_json(self, path: str, params: dict[str, str]) -> dict:
        self.calls.append((path, params))
        return {
            "id": 900,
            "name": "Fixture Series",
            "first_air_date": "2020-01-01",
            "overview": "Series plot",
            "seasons": [
                {
                    "season_number": 0,
                    "name": "Specials",
                    "episodes": [
                        {
                            "episode_number": 1,
                            "name": "A Special",
                            "id": 901,
                            "air_date": "2020-02-01",
                        }
                    ],
                },
                {"season_number": 1, "name": "Season 1", "episodes": []},
            ],
        }


def test_tmdb_search_fetch_normalize_locale_attribution_and_provenance() -> None:
    transport = FixtureTransport()
    provider = TmdbProvider(TmdbConfig(api_token="env:TMDB_TOKEN"), transport)
    results = provider.search("Spirited Away", "ru-RU")
    result = results[0]
    assert [(value.external_id, value.kind.value) for value in results] == [
        ("129", "movie"),
        ("200", "series"),
    ]
    assert result.locale == "ru-RU"
    assert transport.calls[:2] == [
        ("/search/movie", {"query": "Spirited Away", "language": "ru-RU"}),
        ("/search/tv", {"query": "Spirited Away", "language": "ru-RU"}),
    ]
    raw = provider.fetch("movie", "129", "ja-JP")
    assert raw["id"] == 129 and raw["overview"] == "A journey."
    assert transport.calls[-1] == ("/movie/129", {"language": "ja-JP"})
    normalized = provider.normalize(raw, "movie", "129", "ja-JP")
    assert normalized.titles["ja-JP"] == "Spirited Away"
    assert normalized.provenance.provider_key == "tmdb"
    assert "TMDB" in provider.attribution().notice
    normalized_again = provider.normalize(
        FixtureTransport().get_json("/movie/129", {}), "movie", "129", "en-US"
    )
    assert normalized_again.provider_ids == {"tmdb": "129"}


def test_tmdb_calendar_month_boundaries_and_manual_never_expires() -> None:
    provider = TmdbProvider(TmdbConfig(api_token="env:TMDB_TOKEN"), FixtureTransport())
    created = datetime(2024, 8, 31, 12, tzinfo=UTC)
    retention = provider.retention_for(created)
    assert retention.refresh_after == datetime(2025, 1, 31, 12, tzinfo=UTC)
    assert retention.expires_at == datetime(2025, 2, 28, 12, tzinfo=UTC)
    assert (
        provider.plan_retention(retention, datetime(2025, 1, 31, 12, tzinfo=UTC)).kind
        is RetentionActionKind.REFRESH
    )
    assert (
        provider.plan_retention(retention, datetime(2025, 2, 28, 12, tzinfo=UTC)).kind
        is RetentionActionKind.PURGE
    )


def test_tmdb_normalizes_series_specials_in_season_zero() -> None:
    transport = SeriesTransport()
    provider = TmdbProvider(TmdbConfig(api_token="env:TMDB_TOKEN"), transport)
    raw = provider.fetch("series", "900", "en-US")
    assert transport.calls == [("/tv/900", {"language": "en-US"})]
    normalized = provider.normalize(raw, "series", "900", "en-US")
    assert normalized.kind.value == "series"
    assert normalized.seasons[0].number == 0
    assert normalized.seasons[0].episodes[0].provider_ids == {"tmdb": "901"}
    assert normalized.seasons[0].episodes[0].ordering == 1


def test_generic_purge_preserves_envelope_overrides_identity_and_acquisition(database) -> None:
    service = CatalogService(database)
    provider = TmdbProvider(TmdbConfig(api_token="env:TMDB_TOKEN"), FixtureTransport())
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
    transport = FixtureTransport()
    provider = TmdbProvider(TmdbConfig(api_token="env:TMDB_TOKEN"), transport)
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


def test_removed_configuration_still_executes_registered_expiry_purge(database) -> None:
    service = CatalogService(database)
    active = TmdbProvider(TmdbConfig(api_token="env:TMDB_TOKEN"), FixtureTransport())
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
    retention_only = TmdbProvider.retention_only()
    MaintenanceCoordinator({"tmdb": retention_only}).run(database, datetime(2024, 7, 1, tzinfo=UTC))
    database.refresh(revision)
    assert revision.expired_at is not None
    assert revision.maintenance_status == "purged"


class FailingTransport:
    def get_json(self, path: str, params: dict[str, str]) -> dict:
        raise RuntimeError(
            "failed https://api.example.test/passkey/SECRET/file?api_key=TOKEN#fragment"
        )


def test_tmdb_transport_failures_are_standardized_and_secret_safe() -> None:
    provider = TmdbProvider(TmdbConfig(api_token="env:TMDB_TOKEN"), FailingTransport())
    with pytest.raises(ModuleError) as captured:
        provider.search("secret", "en-US")
    error = captured.value
    rendered = f"{error} {error.safe_details}"
    assert error.code == "metadata_provider_unavailable"
    assert "SECRET" not in rendered
    assert "TOKEN" not in rendered
    assert "passkey" not in rendered
    assert "api_key" not in rendered
    assert "https://api.example.test" in rendered
