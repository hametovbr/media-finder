from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

import pytest
from fastapi.testclient import TestClient
from media_finder_server import create_legacy_module_registry

from media_finder.api import create_app
from media_finder.db import create_database, migrate_to_head, session_factory
from media_finder.domain import CatalogService
from media_finder.models import Acquisition
from media_finder.naming import EntityType
from media_finder.nfo import render_nfo
from media_finder.sdk.types import (
    Artwork,
    Episode,
    ExportHeader,
    ExportWarning,
    MediaKind,
    NormalizedMetadata,
    Person,
    Provenance,
    Rating,
    RetentionPolicy,
    Season,
)

LEGACY_REGISTRY = create_legacy_module_registry()


def _rich_movie(provider: str = "manual") -> NormalizedMetadata:
    return NormalizedMetadata(
        kind=MediaKind.MOVIE,
        titles={"en-US": "A <Movie> & Home"},
        original_title="Original & Title",
        year=2024,
        plot="Plot <unsafe> & escaped",
        release_date="2024-02-03",
        runtime_minutes=123,
        provider_ids={provider: "42", "imdb": "tt0000042"},
        ratings=(Rating(source="fixture", value=8.5, votes=100),),
        genres=("Drama", "Animation"),
        tags=("family",),
        countries=("Japan",),
        studios=("Fixture Studio",),
        people=(
            Person(name="Director Name", role="director"),
            Person(name="Actor Name", role="actor", character="Hero & Friend"),
        ),
        artwork=(
            Artwork(kind="poster", url="https://images.example.test/poster.jpg", language="en"),
        ),
        provenance=Provenance(
            provider_key=provider, external_id="42", locale="en-US", source_label="Fixture"
        ),
        completeness=1,
        structural_quality=1,
    )


def _series() -> NormalizedMetadata:
    return NormalizedMetadata(
        kind=MediaKind.SERIES,
        titles={"en-US": "Fixture Show"},
        year=2024,
        plot="Show plot",
        provider_ids={"manual": "series"},
        seasons=(
            Season(
                number=0,
                title="Specials",
                plot="Special season",
                provider_ids={"manual": "season-0"},
                episodes=(
                    Episode(
                        number=1,
                        title="Special & One",
                        plot="Special <plot>",
                        air_date="2024-03-04",
                        runtime_minutes=25,
                        provider_ids={"manual": "special-1"},
                        ordering=7,
                    ),
                ),
            ),
            Season(number=1, title="Season One", episodes=(Episode(number=1, title="One"),)),
        ),
        provenance=Provenance(provider_key="manual", external_id="series", locale="en-US"),
    )


def test_movie_nfo_is_rich_structured_and_xml_safe() -> None:
    result = render_nfo(_rich_movie(), entity_type=EntityType.MOVIE)
    root = ElementTree.fromstring(result.xml)

    assert root.tag == "movie"
    assert result.filename == "A Movie & Home (2024).nfo"
    assert root.findtext("title") == "A <Movie> & Home"
    assert root.findtext("originaltitle") == "Original & Title"
    assert root.findtext("plot") == "Plot <unsafe> & escaped"
    assert root.findtext("premiered") == "2024-02-03"
    assert root.findtext("runtime") == "123"
    assert {(node.get("type"), node.text) for node in root.findall("uniqueid")} == {
        ("manual", "42"),
        ("imdb", "tt0000042"),
    }
    assert root.findtext("ratings/rating/value") == "8.5"
    assert [node.text for node in root.findall("genre")] == ["Drama", "Animation"]
    assert root.findtext("actor/role") == "Hero & Friend"
    assert root.find("thumb").get("aspect") == "poster"
    assert "&lt;unsafe&gt; &amp; escaped" in result.xml
    assert all(field not in result.xml for field in ("playcount", "resume", "watched"))


def test_tvshow_season_and_special_episode_nfo_snapshots() -> None:
    tvshow = ElementTree.fromstring(render_nfo(_series(), entity_type=EntityType.TVSHOW).xml)
    season_result = render_nfo(_series(), entity_type=EntityType.SEASON, season_number=0)
    episode_result = render_nfo(
        _series(), entity_type=EntityType.EPISODE, season_number=0, episode_numbers=(1,)
    )
    season = ElementTree.fromstring(season_result.xml)
    episode = ElementTree.fromstring(episode_result.xml)

    assert tvshow.tag == "tvshow" and tvshow.findtext("title") == "Fixture Show"
    assert season.tag == "season" and season.findtext("seasonnumber") == "0"
    assert season_result.filename == "season.nfo"
    assert episode.tag == "episodedetails"
    assert episode.findtext("season") == "0"
    assert episode.findtext("episode") == "1"
    assert episode.findtext("displayepisode") == "7"
    assert episode_result.filename.endswith("S00E01 - Special & One.nfo")


def test_nfo_rejects_entity_mismatch_and_multi_episode() -> None:
    with pytest.raises(ValueError, match="nfo_entity_mismatch"):
        render_nfo(_rich_movie(), entity_type=EntityType.TVSHOW)
    with pytest.raises(ValueError, match="nfo_multi_episode_unsupported"):
        render_nfo(
            _series(), entity_type=EntityType.EPISODE, season_number=1, episode_numbers=(1, 2)
        )


def test_current_and_pinned_nfo_api_adds_provider_owned_warning_headers(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("MEDIA_FINDER_INTEGRATION_TOKEN", "integration-secret")
    url = f"sqlite:///{tmp_path / 'nfo-api.db'}"
    migrate_to_head(url)
    engine = create_database(url)
    expiry = datetime(2025, 6, 1, 12, tzinfo=UTC)
    with session_factory(engine)() as session:
        service = CatalogService(session)
        item, _ = service.get_or_create_item("tmdb", "42", "movie")
        revision = service.add_provider_revision(
            item,
            {"private": "provider-only"},
            _rich_movie("tmdb"),
            {},
            RetentionPolicy(expires_at=expiry),
            datetime(2025, 1, 1, tzinfo=UTC),
        )
        acquisition = Acquisition(
            media_item_id=item.id,
            metadata_revision_id=revision.id,
            idempotency_key="nfo-api",
            naming_profile="jellyfin-v1",
            status="submitted",
        )
        session.add(acquisition)
        session.commit()
        item_id, acquisition_id = item.id, str(acquisition.id)
    engine.dispose()

    app = create_app(
        url,
        integration_token_reference="env:MEDIA_FINDER_INTEGRATION_TOKEN",
        clock=lambda: datetime(2025, 2, 1, tzinfo=UTC),
        providers={"tmdb": LEGACY_REGISTRY.metadata_providers["tmdb"].retention_factory()},
    )
    client = TestClient(app)
    headers = {"Authorization": "Bearer integration-secret"}
    current = client.get(
        f"/api/v1/media-items/{item_id}/exports/nfo",
        headers=headers,
        params={"entity_type": "movie"},
    )
    pinned = client.get(
        f"/api/v1/acquisitions/{acquisition_id}/exports/nfo",
        headers=headers,
        params={"entity_type": "movie"},
    )

    assert current.status_code == pinned.status_code == 200
    assert current.headers["content-type"].startswith("application/xml")
    assert current.headers["content-disposition"] == (
        'attachment; filename="A Movie & Home (2024).nfo"'
    )
    assert current.headers["sunset"] == "Sun, 01 Jun 2025 12:00:00 GMT"
    assert current.headers["x-media-finder-metadata-expires"] == expiry.isoformat()
    assert current.text == pinned.text
    assert "provider-only" not in current.text
    assert not Path("provenance.json").exists()


def test_multi_episode_nfo_api_has_stable_machine_code(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MEDIA_FINDER_INTEGRATION_TOKEN", "integration-secret")
    url = f"sqlite:///{tmp_path / 'nfo-multi.db'}"
    migrate_to_head(url)
    engine = create_database(url)
    with session_factory(engine)() as session:
        item = CatalogService(session).create_manual_item(_series())
        item_id = item.id
    engine.dispose()
    client = TestClient(
        create_app(url, integration_token_reference="env:MEDIA_FINDER_INTEGRATION_TOKEN")
    )

    response = client.get(
        f"/api/v1/media-items/{item_id}/exports/nfo",
        headers={"Authorization": "Bearer integration-secret"},
        params={"entity_type": "episode", "season_number": 1, "episode_numbers": [1, 2]},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "nfo_multi_episode_unsupported"
    assert response.json()["error"]["details"] == {"recommendation": "split_episodes"}


def test_nfo_content_disposition_supports_safe_unicode_filename(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("MEDIA_FINDER_INTEGRATION_TOKEN", "integration-secret")
    url = f"sqlite:///{tmp_path / 'nfo-unicode.db'}"
    migrate_to_head(url)
    engine = create_database(url)
    metadata = _rich_movie().model_copy(
        update={
            "titles": {"ru-RU": "Мой фильм"},
            "provenance": _rich_movie().provenance.model_copy(update={"locale": "ru-RU"}),
        }
    )
    with session_factory(engine)() as session:
        item = CatalogService(session).create_manual_item(metadata)
        item_id = item.id
    engine.dispose()
    client = TestClient(
        create_app(url, integration_token_reference="env:MEDIA_FINDER_INTEGRATION_TOKEN")
    )

    response = client.get(
        f"/api/v1/media-items/{item_id}/exports/nfo",
        headers={"Authorization": "Bearer integration-secret"},
        params={"entity_type": "movie"},
    )

    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith(
        "attachment; filename=\"metadata.nfo\"; filename*=UTF-8''"
    )
    assert (
        "%D0%9C%D0%BE%D0%B9%20%D1%84%D0%B8%D0%BB%D1%8C%D0%BC"
        in response.headers["content-disposition"]
    )


@pytest.mark.parametrize(
    ("entity_type", "season_number", "episode_numbers"),
    [
        (EntityType.MOVIE, None, ()),
        (EntityType.TVSHOW, None, ()),
        (EntityType.SEASON, 0, ()),
        (EntityType.EPISODE, 0, (1,)),
    ],
)
def test_nfo_sanitizes_invalid_xml_10_codepoints_in_all_projection_boundaries(
    entity_type: EntityType,
    season_number: int | None,
    episode_numbers: tuple[int, ...],
) -> None:
    invalid = "safe\x00\x01\ud800\ufffevalue"
    if entity_type is EntityType.MOVIE:
        metadata = _rich_movie().model_copy(
            update={
                "titles": {"en-US": invalid},
                "original_title": invalid,
                "plot": invalid,
                "provider_ids": {invalid: invalid},
                "ratings": (Rating(source=invalid, value=8.5),),
                "genres": (invalid,),
                "tags": (invalid,),
                "countries": (invalid,),
                "studios": (invalid,),
                "people": (Person(name=invalid, role=invalid, character=invalid),),
                "artwork": (
                    Artwork(
                        kind=invalid,
                        url="https://images.example.test/poster.jpg",
                        language=invalid,
                    ),
                ),
            }
        )
    else:
        episode = Episode(
            number=1,
            title=invalid,
            plot=invalid,
            provider_ids={invalid: invalid},
        )
        season = Season(
            number=0,
            title=invalid,
            plot=invalid,
            provider_ids={invalid: invalid},
            episodes=(episode,),
        )
        metadata = NormalizedMetadata(
            kind=MediaKind.SERIES,
            titles={"en-US": invalid},
            original_title=invalid,
            plot=invalid,
            provider_ids={invalid: invalid},
            ratings=(Rating(source=invalid, value=7),),
            genres=(invalid,),
            tags=(invalid,),
            countries=(invalid,),
            studios=(invalid,),
            people=(Person(name=invalid, role=invalid, character=invalid),),
            artwork=(
                Artwork(
                    kind=invalid,
                    url="https://images.example.test/poster.jpg",
                    language=invalid,
                ),
            ),
            seasons=(season,),
            provenance=Provenance(provider_key="manual", external_id="invalid-xml", locale="en-US"),
        )

    result = render_nfo(
        metadata,
        entity_type=entity_type,
        season_number=season_number,
        episode_numbers=episode_numbers,
    )

    ElementTree.fromstring(result.xml)
    assert all(
        character in "\t\n\r"
        or 0x20 <= ord(character) <= 0xD7FF
        or 0xE000 <= ord(character) <= 0xFFFD
        or 0x10000 <= ord(character) <= 0x10FFFF
        for character in result.xml
    )


def test_nfo_api_defensively_revalidates_forged_provider_warning(
    tmp_path: Path, monkeypatch
) -> None:
    class ForgedWarningProvider:
        def export_warning(self, policy, now) -> ExportWarning:
            del policy, now
            forged = ExportHeader.model_construct(name="Set-Cookie", value="session=unsafe")
            return ExportWarning.model_construct(headers=(forged,))

    monkeypatch.setenv("MEDIA_FINDER_INTEGRATION_TOKEN", "integration-secret")
    url = f"sqlite:///{tmp_path / 'forged-warning.db'}"
    migrate_to_head(url)
    engine = create_database(url)
    with session_factory(engine)() as session:
        service = CatalogService(session)
        item, _ = service.get_or_create_item("forged", "42", "movie")
        service.add_provider_revision(
            item,
            {"private": True},
            _rich_movie("forged"),
            {},
            RetentionPolicy(expires_at=datetime(2026, 1, 1, tzinfo=UTC)),
            datetime(2025, 1, 1, tzinfo=UTC),
        )
        item_id = item.id
    engine.dispose()
    client = TestClient(
        create_app(
            url,
            integration_token_reference="env:MEDIA_FINDER_INTEGRATION_TOKEN",
            clock=lambda: datetime(2025, 2, 1, tzinfo=UTC),
            providers={"forged": ForgedWarningProvider()},  # type: ignore[dict-item]
        )
    )

    response = client.get(
        f"/api/v1/media-items/{item_id}/exports/nfo",
        headers={"Authorization": "Bearer integration-secret"},
        params={"entity_type": "movie"},
    )

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "set-cookie" not in response.headers
