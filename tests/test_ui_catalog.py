import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from media_finder.domain import CatalogService, RevisionInput
from media_finder.models import Acquisition, Collection, MediaItem
from media_finder.sdk.types import MediaKind, NormalizedMetadata, Provenance
from media_finder_core.platform.database import migrate_to_head, session_factory
from media_finder_server import create_ui_app


def _csrf(response_text: str) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', response_text)
    assert match is not None
    return match.group(1)


@pytest.fixture
def catalog_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database_url = f"sqlite:///{tmp_path / 'catalog.db'}"
    migrate_to_head(database_url)
    monkeypatch.setenv("MEDIA_FINDER_UI_SECRET", "a sufficiently long test session secret")
    app = create_ui_app(
        database_url,
        session_secret_reference="env:MEDIA_FINDER_UI_SECRET",
    )
    sessions = session_factory(app.state.engine)
    with sessions() as session:
        collection = Collection(name="Animation")
        session.add(collection)
        item = MediaItem(
            provider_key="manual",
            external_id=str(uuid4()),
            kind="series",
            collection=collection,
        )
        session.add(item)
        session.flush()
        normalized = NormalizedMetadata(
            kind=MediaKind.SERIES,
            titles={"en": "Handmade Series", "ru": "Ручной сериал"},
            year=1996,
            provenance=Provenance(provider_key="manual", external_id=item.external_id, locale="en"),
        )
        revision = CatalogService(session).add_revision(item, RevisionInput(normalized=normalized))
        older = Acquisition(
            id=(older_id := uuid4()),
            correlation=f"mf-acq-{older_id}",
            release_provider_id="fixture-release",
            release_provider_version="1.0.0",
            download_client_module_id="fixture-download",
            download_client_module_version="1.0.0",
            media_item_id=item.id,
            metadata_revision_id=revision.id,
            idempotency_key="old",
            naming_profile="jellyfin-v1",
            status="submitted",
            destination="series",
            created_at=datetime.now(UTC) - timedelta(hours=1),
        )
        latest = Acquisition(
            id=(latest_id := uuid4()),
            correlation=f"mf-acq-{latest_id}",
            release_provider_id="fixture-release",
            release_provider_version="1.0.0",
            download_client_module_id="fixture-download",
            download_client_module_version="1.0.0",
            media_item_id=item.id,
            metadata_revision_id=revision.id,
            idempotency_key="new",
            naming_profile="jellyfin-v1",
            status="pending",
            destination="series",
            created_at=datetime.now(UTC),
        )
        session.add_all([older, latest])
        session.commit()
        app.state.fixture_ids = {"collection": collection.id, "item": item.id}
    return app


def test_catalog_shell_shows_latest_bounded_state_without_progress(catalog_app) -> None:
    with TestClient(catalog_app) as client:
        page = client.get("/")

    assert page.status_code == 200
    assert '<nav aria-label="Collections">' in page.text
    assert 'action="/ui/collections"' in page.text
    assert (
        f'action="/ui/collections/{catalog_app.state.fixture_ids["collection"]}/archive"'
        in page.text
    )
    assert 'data-testid="catalog-card"' in page.text
    assert "Handmade Series" in page.text
    assert "Pending submission" in page.text
    assert "Manual reconciliation may be required." in page.text
    assert "progress" not in page.text.casefold()


def test_collections_items_and_moves_are_archive_only(catalog_app) -> None:
    ids = catalog_app.state.fixture_ids
    with TestClient(catalog_app) as client:
        csrf = _csrf(client.get("/").text)
        created = client.post(
            "/ui/collections",
            data={"csrf": csrf, "name": "Family"},
            follow_redirects=False,
        )
        assert created.status_code == 303

        archived = client.post(
            f"/ui/items/{ids['item']}/archive",
            data={"csrf": csrf},
            follow_redirects=False,
        )
        assert archived.status_code == 303
        restored = client.post(
            f"/ui/items/{ids['item']}/restore",
            data={"csrf": csrf},
            follow_redirects=False,
        )
        assert restored.status_code == 303

        moved = client.post(
            f"/ui/items/{ids['item']}/move",
            data={"csrf": csrf, "collection_id": ""},
            follow_redirects=False,
        )
        assert moved.status_code == 303

    sessions = session_factory(catalog_app.state.engine)
    with sessions() as session:
        item = session.get(MediaItem, ids["item"])
        assert item is not None
        assert item.archived_at is None
        assert item.collection_id is None
        assert session.query(Collection).filter_by(name="Family").one().archived_at is None


def test_item_tabs_are_bounded_htmx_fragments(catalog_app) -> None:
    item_id = catalog_app.state.fixture_ids["item"]
    with TestClient(catalog_app) as client:
        fragment = client.get(
            f"/ui/items/{item_id}/tabs/acquisitions", headers={"HX-Request": "true"}
        )

    assert fragment.status_code == 200
    assert fragment.headers["Vary"] == "HX-Request"
    assert "<html" not in fragment.text
    assert 'aria-live="polite"' in fragment.text
    assert "Pending submission" in fragment.text
    assert "Manual reconciliation may be required." in fragment.text
    assert "/reconcile" in fragment.text
    assert 'name="csrf"' in fragment.text


def test_archived_collection_rejects_moves_until_restored(catalog_app) -> None:
    ids = catalog_app.state.fixture_ids
    with TestClient(catalog_app) as client:
        csrf = _csrf(client.get("/").text)
        archived = client.post(
            f"/ui/collections/{ids['collection']}/archive",
            data={"csrf": csrf},
            follow_redirects=False,
        )
        assert archived.status_code == 303
        rejected = client.post(
            f"/ui/items/{ids['item']}/move",
            data={"csrf": csrf, "collection_id": ids["collection"]},
        )
        assert rejected.status_code == 422
        restored = client.post(
            f"/ui/collections/{ids['collection']}/restore",
            data={"csrf": csrf},
            follow_redirects=False,
        )
        assert restored.status_code == 303

    sessions = session_factory(catalog_app.state.engine)
    with sessions() as session:
        collection = session.get(Collection, ids["collection"])
        assert collection is not None
        assert collection.archived_at is None


def test_visible_collection_and_item_controls_cover_move_archive_and_restore(catalog_app) -> None:
    ids = catalog_app.state.fixture_ids
    with TestClient(catalog_app) as client:
        detail = client.get(f"/items/{ids['item']}")
        assert f'action="/ui/items/{ids["item"]}/move"' in detail.text
        assert 'data-testid="move-item"' in detail.text
        assert f'action="/ui/items/{ids["item"]}/archive"' in detail.text
        csrf = _csrf(detail.text)

        archived_item = client.post(
            f"/ui/items/{ids['item']}/archive",
            data={"csrf": csrf},
            follow_redirects=False,
        )
        assert archived_item.status_code == 303
        archive = client.get("/?archived=1")
        assert f'action="/ui/items/{ids["item"]}/restore"' in archive.text

        archived_collection = client.post(
            f"/ui/collections/{ids['collection']}/archive",
            data={"csrf": csrf},
            follow_redirects=False,
        )
        assert archived_collection.status_code == 303
        archive = client.get("/?archived=1")
        assert f'action="/ui/collections/{ids["collection"]}/restore"' in archive.text
        assert "Animation" in archive.text
