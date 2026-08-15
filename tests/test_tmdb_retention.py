from datetime import UTC, datetime

from media_finder.domain import CatalogService
from media_finder.maintenance import MaintenanceCoordinator, MaintenanceRunner
from media_finder.modules.tmdb import TmdbConfig, TmdbProvider
from media_finder.sdk.types import RetentionActionKind


class FixtureTransport:
    def get_json(self, path: str, params: dict[str, str]) -> dict:
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
    def get_json(self, path: str, params: dict[str, str]) -> dict:
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
    provider = TmdbProvider(TmdbConfig(api_token="env:TMDB_TOKEN"), FixtureTransport())
    result = provider.search("Spirited Away", "ru-RU")[0]
    assert result.external_id == "129" and result.locale == "ru-RU"
    normalized = provider.fetch("movie", "129", "ja-JP")
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
    provider = TmdbProvider(TmdbConfig(api_token="env:TMDB_TOKEN"), SeriesTransport())
    normalized = provider.fetch("series", "900", "en-US")
    assert normalized.kind.value == "series"
    assert normalized.seasons[0].number == 0
    assert normalized.seasons[0].episodes[0].provider_ids == {"tmdb": "901"}
    assert normalized.seasons[0].episodes[0].ordering == 1


def test_generic_purge_preserves_envelope_overrides_identity_and_acquisition(database) -> None:
    service = CatalogService(database)
    provider = TmdbProvider(TmdbConfig(api_token="env:TMDB_TOKEN"), FixtureTransport())
    item, _ = service.get_or_create_item("tmdb", "129", "movie")
    created = datetime(2024, 1, 1, tzinfo=UTC)
    normalized = provider.fetch("movie", "129", "en-US")
    revision = service.add_provider_revision(
        item, normalized, {"title": "Custom"}, provider.retention_for(created), created
    )
    coordinator = MaintenanceCoordinator({"tmdb": provider})
    coordinator.run(database, datetime(2024, 7, 1, tzinfo=UTC))
    database.refresh(revision)
    assert revision.raw_payload is None
    assert revision.normalized_payload is None
    assert revision.effective_payload is None
    assert revision.overrides_payload == {"title": "Custom"}
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
