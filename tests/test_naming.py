from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from media_finder.api import create_app
from media_finder.db import create_database, migrate_to_head, session_factory
from media_finder.domain import CatalogService
from media_finder.models import Acquisition
from media_finder.naming import EntityType, render_naming
from media_finder.sdk.types import Episode, MediaKind, NormalizedMetadata, Provenance, Season


def _series(title: str = "Мой: сериал / ../ CON") -> NormalizedMetadata:
    return NormalizedMetadata(
        kind=MediaKind.SERIES,
        titles={"ru-RU": title},
        year=2024,
        seasons=(
            Season(
                number=0,
                title="Specials",
                episodes=(Episode(number=1, title="Special: начало", ordering=7),),
            ),
            Season(
                number=1,
                title="Season 1",
                episodes=(
                    Episode(number=1, title="Первая / серия"),
                    Episode(number=2, title="Вторая серия"),
                ),
            ),
        ),
        provenance=Provenance(provider_key="manual", external_id="series", locale="ru-RU"),
        completeness=1,
        structural_quality=1,
    )


def test_extension_independent_episode_naming_snapshot() -> None:
    snapshots = {
        extension: render_naming(
            _series("Волшебный сериал"),
            entity_type=EntityType.EPISODE,
            season_number=1,
            episode_numbers=(1, 2),
            target_extension=extension,
        ).model_dump()
        for extension in (None, "mkv", "mp4", "webm")
    }

    assert snapshots[None] == {
        "profile": "jellyfin-v1",
        "relative_directory": "Волшебный сериал (2024)/Season 01",
        "basename": "Волшебный сериал - S01E01-E02",
        "target_extension": None,
        "relative_path": "Волшебный сериал (2024)/Season 01/Волшебный сериал - S01E01-E02",
        "nfo_filename": "Волшебный сериал - S01E01-E02.nfo",
    }
    for extension in ("mkv", "mp4", "webm"):
        assert snapshots[extension]["relative_directory"] == snapshots[None]["relative_directory"]
        assert snapshots[extension]["basename"] == snapshots[None]["basename"]
        assert snapshots[extension]["target_extension"] == extension
        assert snapshots[extension]["relative_path"].endswith(f".{extension}")


def test_movie_special_and_portable_sanitation() -> None:
    movie = NormalizedMetadata(
        kind=MediaKind.MOVIE,
        titles={"en-US": "CON"},
        year=2001,
        provenance=Provenance(provider_key="manual", external_id="movie", locale="en-US"),
    )
    movie_name = render_naming(movie, entity_type=EntityType.MOVIE)
    special = render_naming(
        _series(),
        entity_type=EntityType.EPISODE,
        season_number=0,
        episode_numbers=(1,),
        target_extension="MP4",
    )

    assert movie_name.relative_directory == "_CON (2001)"
    assert special.target_extension == "mp4"
    assert "Season 00" in special.relative_directory
    assert "S00E01" in special.basename
    assert ".." not in special.relative_path
    assert not any(character in special.relative_path for character in '<>:"|?*\\')
    assert "Мой" in special.relative_path


@pytest.mark.parametrize("extension", [".mkv", "../mkv", "m kv", "", "x" * 11])
def test_unsafe_extensions_are_rejected(extension: str) -> None:
    with pytest.raises(ValueError, match="target_extension_invalid"):
        render_naming(
            _series(),
            entity_type=EntityType.TVSHOW,
            target_extension=extension,
        )


def test_selector_and_media_kind_mismatch_are_rejected() -> None:
    with pytest.raises(ValueError, match="naming_selector_invalid"):
        render_naming(_series(), entity_type=EntityType.EPISODE, season_number=1)
    with pytest.raises(ValueError, match="naming_entity_mismatch"):
        render_naming(_series(), entity_type=EntityType.MOVIE)


def test_current_and_pinned_naming_endpoints_use_the_fixed_profile(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("MEDIA_FINDER_INTEGRATION_TOKEN", "integration-secret")
    url = f"sqlite:///{tmp_path / 'naming-api.db'}"
    migrate_to_head(url)
    engine = create_database(url)
    with session_factory(engine)() as session:
        item = CatalogService(session).create_manual_item(_series("Волшебный сериал"))
        revision = item.current_revision
        assert revision is not None
        acquisition = Acquisition(
            media_item_id=item.id,
            metadata_revision_id=revision.id,
            idempotency_key="naming-api",
            naming_profile="jellyfin-v1",
            status="submitted",
        )
        session.add(acquisition)
        session.commit()
        item_id, acquisition_id = item.id, str(acquisition.id)
    engine.dispose()
    client = TestClient(
        create_app(url, integration_token_reference="env:MEDIA_FINDER_INTEGRATION_TOKEN")
    )
    headers = {"Authorization": "Bearer integration-secret"}
    params = {
        "entity_type": "episode",
        "season_number": 1,
        "episode_numbers": [1, 2],
        "target_extension": "webm",
    }

    current = client.get(
        f"/api/v1/media-items/{item_id}/exports/naming", headers=headers, params=params
    )
    pinned = client.get(
        f"/api/v1/acquisitions/{acquisition_id}/exports/naming",
        headers=headers,
        params=params,
    )

    assert current.status_code == pinned.status_code == 200
    assert current.json() == pinned.json()
    assert current.json()["relative_path"].endswith("/Волшебный сериал - S01E01-E02.webm")
    invalid = client.get(
        f"/api/v1/media-items/{item_id}/exports/naming",
        headers=headers,
        params={"entity_type": "tvshow", "target_extension": "../mkv"},
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "request_validation_failed"
    incomplete = client.get(
        f"/api/v1/media-items/{item_id}/exports/naming",
        headers=headers,
        params={"entity_type": "episode", "season_number": 1},
    )
    assert incomplete.status_code == 422
    assert incomplete.json()["error"]["code"] == "request_validation_failed"
