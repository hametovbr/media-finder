import json
import re
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from media_finder.domain import CatalogService, RevisionInput
from media_finder.models import DownloadClientInstance, MediaItem, MetadataRevision
from media_finder.sdk.types import MediaKind, NormalizedMetadata, Provenance
from media_finder_core.exports import EntityType, render_naming, render_nfo
from media_finder_core.platform.database import migrate_to_head, session_factory
from media_finder_sdk import NormalizedMetadata as CoreNormalizedMetadata
from media_finder_server import create_ui_app
from sqlalchemy import select


def _core_metadata(metadata: NormalizedMetadata) -> CoreNormalizedMetadata:
    payload = metadata.model_dump(mode="json")
    provenance = payload["provenance"]
    provenance["provider_id"] = provenance.pop("provider_key")
    return CoreNormalizedMetadata.model_validate(payload)


def _csrf(text: str) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', text)
    assert match
    return match.group(1)


def _external_id(text: str) -> str:
    match = re.search(r'name="external_id" value="([^"]+)"', text)
    assert match
    return match.group(1)


def _draft_token(text: str) -> str:
    match = re.search(r'name="draft_token" value="([^"]+)"', text)
    assert match
    return match.group(1)


@pytest.fixture
def acceptance_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    url = f"sqlite:///{tmp_path / 'acceptance.db'}"
    migrate_to_head(url)
    monkeypatch.setenv("MEDIA_FINDER_UI_SECRET", "a sufficiently long test session secret")
    return create_ui_app(url, session_secret_reference="env:MEDIA_FINDER_UI_SECRET")


def test_rich_manual_import_edit_preserves_unedited_contract_fields(acceptance_app) -> None:
    identity = str(uuid4())
    document = {
        "schema_version": "1",
        "external_id": identity,
        "kind": "series",
        "locale": "en",
        "titles": {"en": "Rich show", "ru": "Богатый сериал"},
        "original_title": "Original",
        "year": 2024,
        "plot": "Old plot",
        "release_date": "2024-01-02",
        "runtime_minutes": 42,
        "provider_ids": {"imdb": "tt123"},
        "ratings": [{"source": "manual", "value": 8.5, "votes": 12}],
        "genres": ["Animation"],
        "tags": ["family"],
        "countries": ["Japan"],
        "studios": ["Studio"],
        "people": [{"name": "Director", "role": "director"}],
        "artwork": [
            {"kind": "poster", "url": "https://images.example.test/poster.jpg", "language": "en"}
        ],
        "seasons": [
            {
                "number": 0,
                "title": "Specials",
                "plot": "Season plot",
                "provider_ids": {"tmdb": "s0"},
                "episodes": [
                    {
                        "number": 1,
                        "title": "Old special",
                        "plot": "Episode plot",
                        "air_date": "2024-02-03",
                        "runtime_minutes": 25,
                        "provider_ids": {"tmdb": "e1"},
                        "ordering": 7,
                    }
                ],
            },
            {"number": 1, "title": "Removed", "episodes": []},
        ],
    }
    with TestClient(acceptance_app) as client:
        csrf = _csrf(client.get("/").text)
        created = client.post(
            "/ui/manual/import",
            data={"csrf": csrf, "document": json.dumps(document)},
            follow_redirects=False,
        )
        item_id = created.headers["location"].split("/")[2].split("?")[0]
        edit = client.get(f"/items/{item_id}/edit")
        assert 'name="season_0_source_number" value="0"' in edit.text
        pending = client.post(
            "/ui/manual/save",
            data={
                "csrf": csrf,
                "item_id": item_id,
                "external_id": _external_id(edit.text),
                "kind": "series",
                "metadata_locale": "en",
                "title": "Rich show revised",
                "original_title": "Original",
                "year": "2024",
                "plot": "New plot",
                "release_date": "2024-01-02",
                "runtime_minutes": "42",
                "season_0_source_number": "0",
                "season_0_number": "0",
                "season_0_title": "Specials",
                "season_0_episode_0_source_number": "1",
                "season_0_episode_0_number": "1",
                "season_0_episode_0_title": "Revised special",
                "season_0_episode_0_plot": "Episode plot",
            },
        )
        confirmed = client.post(
            "/ui/manual/confirm",
            data={"csrf": csrf, "draft_token": _draft_token(pending.text)},
            follow_redirects=False,
        )
        assert confirmed.status_code == 303

    sessions = session_factory(acceptance_app.state.engine)
    with sessions() as database:
        item = database.get(MediaItem, item_id)
        assert item is not None and item.current_revision is not None
        revisions = list(
            database.scalars(
                select(MetadataRevision)
                .where(MetadataRevision.media_item_id == item_id)
                .order_by(MetadataRevision.revision_number)
            )
        )
        assert len(revisions) == 2
        assert revisions[0].effective_payload["titles"]["en"] == "Rich show"
        metadata = NormalizedMetadata.model_validate(item.current_revision.effective_payload)
        assert metadata.titles == {"en": "Rich show revised", "ru": "Богатый сериал"}
        assert metadata.original_title == "Original"
        assert str(metadata.release_date) == "2024-01-02"
        assert metadata.runtime_minutes == 42
        assert metadata.provider_ids == {"imdb": "tt123"}
        assert metadata.ratings[0].votes == 12
        assert metadata.genres == ("Animation",)
        assert metadata.tags == ("family",)
        assert metadata.countries == ("Japan",)
        assert metadata.studios == ("Studio",)
        assert metadata.people[0].name == "Director"
        assert str(metadata.artwork[0].url) == "https://images.example.test/poster.jpg"
        assert len(metadata.seasons) == 1
        assert metadata.seasons[0].plot == "Season plot"
        assert metadata.seasons[0].provider_ids == {"tmdb": "s0"}
        episode = metadata.seasons[0].episodes[0]
        assert episode.title == "Revised special"
        assert str(episode.air_date) == "2024-02-03"
        assert episode.runtime_minutes == 25
        assert episode.provider_ids == {"tmdb": "e1"}
        assert episode.ordering == 7
        exported_metadata = _core_metadata(metadata)
        assert (
            "Rich show revised"
            in render_naming(
                exported_metadata,
                entity_type=EntityType.EPISODE,
                season_number=0,
                episode_numbers=(1,),
            ).relative_path
        )
        assert (
            "<displayepisode>7</displayepisode>"
            in render_nfo(
                exported_metadata,
                entity_type=EntityType.EPISODE,
                season_number=0,
                episode_numbers=(1,),
            ).xml
        )


def test_existing_identity_cannot_change_media_kind(database) -> None:
    catalog = CatalogService(database)
    item, _ = catalog.get_or_create_item("manual", str(uuid4()), MediaKind.MOVIE)
    with pytest.raises(ValueError, match="provider_identity_mismatch"):
        catalog.get_or_create_item("manual", item.external_id, MediaKind.SERIES)
    series = NormalizedMetadata(
        kind=MediaKind.SERIES,
        titles={"en": "Wrong"},
        provenance=Provenance(provider_key="manual", external_id=item.external_id, locale="en"),
    )
    with pytest.raises(ValueError, match="provider_identity_mismatch"):
        catalog.add_revision(item, RevisionInput(normalized=series))


def test_metadata_locale_inherits_ui_then_persists_independently(acceptance_app) -> None:
    with TestClient(acceptance_app) as client:
        home = client.get("/", headers={"Accept-Language": "ru"})
        csrf = _csrf(home.text)
        manual = client.get("/add/manual", headers={"Accept-Language": "ru"})
        assert '<option value="ru" selected>' in manual.text
        selected = client.post(
            "/ui/metadata-locale",
            data={"csrf": csrf, "metadata_locale": "en"},
            headers={"referer": str(client.base_url) + "/add"},
            follow_redirects=False,
        )
        assert selected.status_code == 303
        switched = client.post(
            "/ui/locale",
            data={"csrf": csrf, "locale": "en"},
            follow_redirects=False,
        )
        assert switched.status_code == 303
        assert '<option value="en" selected>' in client.get("/add/manual").text


def test_catalog_renders_safe_lazy_poster_and_placeholder(acceptance_app) -> None:
    sessions = session_factory(acceptance_app.state.engine)
    with sessions() as database:
        catalog = CatalogService(database)
        with_poster, _ = catalog.get_or_create_item("tmdb", "42", "movie")
        catalog.add_revision(
            with_poster,
            RevisionInput(
                normalized=NormalizedMetadata.model_validate(
                    {
                        "kind": "movie",
                        "titles": {"en": "Poster"},
                        "artwork": [
                            {
                                "kind": "poster",
                                "url": "https://images.example.test/poster.jpg",
                            }
                        ],
                        "provenance": {
                            "provider_key": "tmdb",
                            "external_id": with_poster.external_id,
                            "locale": "en",
                        },
                    }
                )
            ),
        )
        without, _ = catalog.get_or_create_item("manual", str(uuid4()), "movie")
        catalog.add_revision(
            without,
            RevisionInput(
                normalized=NormalizedMetadata(
                    kind=MediaKind.MOVIE,
                    titles={"en": "Placeholder"},
                    provenance=Provenance(
                        provider_key="manual", external_id=without.external_id, locale="en"
                    ),
                )
            ),
        )
    with TestClient(acceptance_app) as client:
        page = client.get("/")
    assert 'src="https://images.example.test/poster.jpg"' in page.text
    assert 'loading="lazy"' in page.text
    assert 'alt="Poster poster"' in page.text
    assert 'data-testid="poster-placeholder"' in page.text


def test_legacy_download_client_lifecycle_is_absent_and_unreachable(
    acceptance_app,
) -> None:
    sessions = session_factory(acceptance_app.state.engine)
    with sessions() as database:
        instance = DownloadClientInstance(
            name="Living room", module_key="qbittorrent", config_payload={}
        )
        item = MediaItem(provider_key="manual", external_id=str(uuid4()), kind="movie")
        database.add_all([instance, item])
        database.flush()
        CatalogService(database).add_revision(
            item,
            RevisionInput(
                normalized=NormalizedMetadata(
                    kind=MediaKind.MOVIE,
                    titles={"en": "Client lifecycle"},
                    provenance=Provenance(
                        provider_key="manual", external_id=item.external_id, locale="en"
                    ),
                )
            ),
        )
        instance_id, item_id = instance.id, item.id
    with TestClient(acceptance_app) as client:
        settings = client.get("/settings")
        csrf = _csrf(settings.text)
        assert f'action="/ui/settings/clients/{instance_id}/archive"' not in settings.text
        archived = client.post(
            f"/ui/settings/clients/{instance_id}/archive",
            data={"csrf": csrf},
            follow_redirects=False,
        )
        assert archived.status_code in {404, 405}
        unavailable = client.post(
            f"/ui/clients/{instance_id}/destinations",
            data={"csrf": csrf},
        )
        assert unavailable.status_code in {404, 405}
        settings = client.get("/settings?clients=archived")
        assert "Archived download clients" not in settings.text
        assert f'action="/ui/settings/clients/{instance_id}/restore"' not in settings.text
        release = client.get(f"/items/{item_id}/releases")
        assert "Living room" not in release.text
        restored = client.post(
            f"/ui/settings/clients/{instance_id}/restore",
            data={"csrf": csrf},
            follow_redirects=False,
        )
        assert restored.status_code in {404, 405}

    with sessions() as database:
        persisted = database.get(DownloadClientInstance, instance_id)
        assert persisted is not None and persisted.system_owned is False
