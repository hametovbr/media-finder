import json
import re
from pathlib import Path

import pytest
from acquisition_fakes import StaticAcquisitionModules
from fastapi.testclient import TestClient
from media_finder_core.acquisition import ReleaseSelectionCache, ReleaseSelectionService
from media_finder_core.acquisition.persistence import AcquisitionRecord as Acquisition
from media_finder_core.catalog.persistence import (
    MediaItemRecord as MediaItem,
)
from media_finder_core.catalog.persistence import (
    MetadataRevisionRecord as MetadataRevision,
)
from media_finder_core.platform.database import migrate_to_head, session_factory
from media_finder_sdk import (
    MagnetArtifact,
    PrivateReleaseSelection,
    ReleaseCandidate,
    ReleaseSearchQuery,
    SafeReleaseSnapshot,
)
from sqlalchemy import func, select
from ui_fixtures import create_ui_test_app


def _csrf(text: str) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', text)
    assert match
    return match.group(1)


def _token(text: str, test_id: str) -> str:
    match = re.search(rf'data-testid="{test_id}"[\s\S]*?value="([^"]+)"', text)
    assert match
    return match.group(1)


class FakeReleaseProvider:
    def validate(self) -> None:
        return None

    def search(self, query: ReleaseSearchQuery) -> tuple[ReleaseCandidate, ...]:
        return (
            ReleaseCandidate(
                snapshot=SafeReleaseSnapshot(
                    title=f"{query.query}.S01",
                    indexer="Fixture Indexer",
                    guid="fixture-release-1",
                ),
                selection=PrivateReleaseSelection.from_bytes(b"fixture-release"),
            ),
        )

    def resolve(self, selection: PrivateReleaseSelection) -> MagnetArtifact:
        assert selection.payload() == b"fixture-release"
        return MagnetArtifact(uri="magnet:?xt=urn:btih:0123456789012345678901234567890123456789")

    def close(self) -> None:
        return None


@pytest.fixture
def workflow_app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_provider,
    fake_client,
):
    database_url = f"sqlite:///{tmp_path / 'workflow.db'}"
    migrate_to_head(database_url)
    monkeypatch.setenv("MEDIA_FINDER_UI_SECRET", "a sufficiently long test session secret")
    prowlarr = ReleaseSelectionService(
        provider=FakeReleaseProvider(), cache=ReleaseSelectionCache()
    )
    app = create_ui_test_app(
        database_url,
        session_secret_reference="env:MEDIA_FINDER_UI_SECRET",
        providers={
            fake_provider.manifest.module_id: fake_provider,
        },
        acquisition=StaticAcquisitionModules(
            releases=prowlarr,
            download_client=fake_client,
            release_id="prowlarr",
            download_id="qbittorrent",
        ),
    )
    return app


def test_grouped_provider_search_requires_explicit_selection_and_saves_before_release(
    workflow_app,
) -> None:
    with TestClient(workflow_app) as client:
        csrf = _csrf(client.get("/").text)
        page = client.get("/add")
        assert 'name="metadata_locale"' in page.text
        results = client.post(
            "/ui/metadata/search",
            data={"csrf": csrf, "query": "Fixture", "metadata_locale": "en"},
            headers={"HX-Request": "true"},
        )
        assert results.status_code == 200
        assert "<html" not in results.text
        assert 'data-testid="provider-results-fixture-provider"' in results.text
        selection = _token(results.text, "provider-result-token")

        saved = client.post(
            "/ui/metadata/confirm",
            data={"csrf": csrf, "selection_token": selection},
            follow_redirects=False,
        )

    assert saved.status_code == 303
    assert saved.headers["location"].startswith("/items/")
    assert saved.headers["location"].endswith("?saved=1")
    sessions = session_factory(workflow_app.state.engine)
    with sessions() as session:
        assert session.scalar(select(func.count(MediaItem.id))) == 1
        assert session.scalar(select(func.count(Acquisition.id))) == 0


def test_manual_json_and_csv_import_are_atomic(workflow_app) -> None:
    valid = {
        "schema_version": "1",
        "kind": "series",
        "locale": "en",
        "titles": {"en": "Manual Series"},
        "seasons": [{"number": 0, "episodes": [{"number": 1, "title": "Special"}]}],
    }
    with TestClient(workflow_app) as client:
        csrf = _csrf(client.get("/").text)
        invalid = client.post(
            "/ui/manual/import",
            data={"csrf": csrf, "document": "{not-json"},
        )
        assert invalid.status_code == 422
        assert "manual_import_invalid" in invalid.text

        created = client.post(
            "/ui/manual/import",
            data={"csrf": csrf, "document": json.dumps(valid)},
            follow_redirects=False,
        )
        assert created.status_code == 303
        item_id = created.headers["location"].split("/")[2].split("?")[0]

        bad_csv = client.post(
            f"/ui/items/{item_id}/manual/csv",
            data={"csrf": csrf, "content": "season,episode,title\n1,nope,Broken"},
        )
        assert bad_csv.status_code == 422
        assert "manual_import_invalid" in bad_csv.text

    sessions = session_factory(workflow_app.state.engine)
    with sessions() as session:
        item = session.get(MediaItem, item_id)
        assert item is not None
        assert item.kind == "series"
        assert (
            session.scalar(
                select(func.count(MetadataRevision.id)).where(
                    MetadataRevision.media_item_id == item_id
                )
            )
            == 1
        )


def test_release_destinations_submit_idempotently_and_pending_reconcile_is_explicit(
    workflow_app,
) -> None:
    valid = {
        "schema_version": "1",
        "kind": "movie",
        "locale": "en",
        "titles": {"en": "Release Target"},
    }
    with TestClient(workflow_app) as client:
        csrf = _csrf(client.get("/").text)
        created = client.post(
            "/ui/manual/import",
            data={"csrf": csrf, "document": json.dumps(valid)},
            follow_redirects=False,
        )
        item_id = created.headers["location"].split("/")[2].split("?")[0]
        search = client.post(
            f"/ui/items/{item_id}/releases/search",
            data={"csrf": csrf, "query": "Release Target", "indexer": ""},
            headers={"HX-Request": "true"},
        )
        release_token = _token(search.text, "release-result")

        destinations = client.post(
            "/ui/qbittorrent/destinations",
            data={"csrf": csrf},
            headers={"HX-Request": "true"},
        )
        assert '<option value="fixture">Fixture</option>' in destinations.text

        payload = {
            "csrf": csrf,
            "release_token": release_token,
            "destination": "fixture",
            "idempotency_key": "browser-idempotency-1",
        }
        submitted = client.post(
            f"/ui/items/{item_id}/acquisitions",
            data=payload,
            follow_redirects=False,
        )
        repeated = client.post(
            f"/ui/items/{item_id}/acquisitions",
            data=payload,
            follow_redirects=False,
        )

    assert submitted.status_code == 303
    assert repeated.status_code == 303
    sessions = session_factory(workflow_app.state.engine)
    with sessions() as session:
        attempts = list(session.scalars(select(Acquisition)))
        assert len(attempts) == 1
        assert attempts[0].status == "submitted"


def test_settings_first_run_and_about_are_generic_and_provider_attributed(
    workflow_app,
) -> None:
    with TestClient(workflow_app) as client:
        settings = client.get("/settings")
        about = client.get("/about")

    assert settings.status_code == 200
    assert 'data-testid="readiness-checklist"' in settings.text
    assert "Manual metadata" in settings.text
    assert "Prowlarr" in settings.text
    assert "QBITTORRENT_URL" in settings.text
    assert "Manual-only catalog use remains available." in settings.text
    assert 'form action="/ui/settings/' not in settings.text
    assert about.status_code == 200
    assert "MIT" in about.text
    assert "Fixture data" in about.text
