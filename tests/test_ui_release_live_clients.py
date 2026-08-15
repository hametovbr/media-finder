import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from media_finder_sdk import (
    MagnetArtifact,
    PrivateReleaseSelection,
    ReleaseCandidate,
    ReleaseSearchQuery,
    SafeReleaseSnapshot,
)
from sqlalchemy import select

from media_finder.db import migrate_to_head, session_factory
from media_finder.models import Acquisition, MediaItem
from media_finder.release_selection import ReleaseSelectionCache, ReleaseSelectionService
from media_finder.sdk.types import CorrelationResult, DownloadDestination, SubmissionResult
from media_finder.system_clients import SYSTEM_QBITTORRENT_ID
from media_finder.ui import create_ui_app


def _csrf(text: str) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', text)
    assert match
    return match.group(1)


def _value(text: str, test_id: str) -> str:
    match = re.search(rf'data-testid="{test_id}"[\s\S]*?value="([^"]+)"', text)
    assert match
    return match.group(1)


class FakeReleaseProvider:
    def validate(self) -> None:
        return None

    def search(self, query: ReleaseSearchQuery) -> tuple[ReleaseCandidate, ...]:
        return (
            ReleaseCandidate(
                snapshot=SafeReleaseSnapshot(title=query.query, indexer="Fixture Indexer"),
                selection=PrivateReleaseSelection.from_bytes(b"fixture-release"),
            ),
        )

    def resolve(self, selection: PrivateReleaseSelection) -> MagnetArtifact:
        assert selection.payload() == b"fixture-release"
        return MagnetArtifact(uri="magnet:?xt=urn:btih:0123456789012345678901234567890123456789")

    def close(self) -> None:
        return None


class MutableClient:
    def __init__(self) -> None:
        self.destinations = [DownloadDestination(key="movies", label="MOVIES")]
        self.tasks: dict[str, str] = {}

    def list_destinations(self) -> list[DownloadDestination]:
        return list(self.destinations)

    def submit(self, artifact, destination: str, correlation: str) -> SubmissionResult:
        self.tasks[correlation] = destination
        return SubmissionResult(accepted=True, external_task_id="task", correlation=correlation)

    def find_by_correlation(self, correlation: str) -> CorrelationResult:
        return CorrelationResult(
            found=correlation in self.tasks,
            correlation=correlation,
            external_task_id="task" if correlation in self.tasks else None,
        )


@pytest.fixture
def release_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database_url = f"sqlite:///{tmp_path / 'release-live.db'}"
    migrate_to_head(database_url)
    monkeypatch.setenv("MEDIA_FINDER_UI_SECRET", "a sufficiently long test session secret")
    qbittorrent = MutableClient()
    app = create_ui_app(
        database_url,
        session_secret_reference="env:MEDIA_FINDER_UI_SECRET",
        prowlarr=ReleaseSelectionService(FakeReleaseProvider(), ReleaseSelectionCache()),
        client_loader=lambda _: qbittorrent,
    )
    app.state.fake_client = qbittorrent
    return app


def _create_item_and_release(client: TestClient, csrf: str) -> tuple[str, str]:
    created = client.post(
        "/ui/manual/import",
        data={
            "csrf": csrf,
            "document": json.dumps(
                {
                    "schema_version": "1",
                    "kind": "movie",
                    "locale": "en",
                    "titles": {"en": "Target"},
                }
            ),
        },
        follow_redirects=False,
    )
    item_id = created.headers["location"].split("/")[2].split("?")[0]
    searched = client.post(
        f"/ui/items/{item_id}/releases/search",
        data={"csrf": csrf, "query": "Target", "indexer": ""},
        headers={"HX-Request": "true"},
    )
    return item_id, _value(searched.text, "release-result")


def test_release_page_implicitly_loads_the_single_live_qbittorrent_destinations(
    release_app,
) -> None:
    with TestClient(release_app) as client:
        csrf = _csrf(client.get("/").text)
        item_id, _ = _create_item_and_release(client, csrf)
        page = client.get(f"/items/{item_id}/releases")
        destinations = client.post(
            "/ui/qbittorrent/destinations",
            data={"csrf": csrf},
            headers={"HX-Request": "true"},
        )

    assert 'hx-post="/ui/qbittorrent/destinations"' in page.text
    assert 'name="client_instance_id"' not in page.text
    assert '<option value="movies">MOVIES</option>' in destinations.text


def test_destination_drift_returns_current_choices_and_keeps_release_token_reusable(
    release_app,
) -> None:
    with TestClient(release_app) as client:
        csrf = _csrf(client.get("/").text)
        item_id, release_token = _create_item_and_release(client, csrf)
        release_app.state.fake_client.destinations = [
            DownloadDestination(key="current", label="CURRENT")
        ]
        payload = {
            "csrf": csrf,
            "release_token": release_token,
            "destination": "stale",
            "idempotency_key": "drift-key",
        }

        drifted = client.post(f"/ui/items/{item_id}/acquisitions", data=payload)
        assert drifted.status_code == 409
        assert 'data-error-code="download_destination_unavailable"' in drifted.text
        assert 'name="client_instance_id"' not in drifted.text
        assert '<option value="current">CURRENT</option>' in drifted.text

        payload["destination"] = "current"
        submitted = client.post(
            f"/ui/items/{item_id}/acquisitions", data=payload, follow_redirects=False
        )

    assert submitted.status_code == 303
    sessions = session_factory(release_app.state.engine)
    with sessions() as database:
        attempts = list(database.scalars(select(Acquisition)))
    assert len(attempts) == 1
    assert attempts[0].download_client_instance_id == SYSTEM_QBITTORRENT_ID


def test_legacy_client_destination_route_is_absent_and_errors_remain_safe(release_app) -> None:
    with TestClient(release_app, raise_server_exceptions=False) as client:
        csrf = _csrf(client.get("/").text)
        item_id, _ = _create_item_and_release(client, csrf)
        legacy = client.post("/ui/clients/destinations", data={"csrf": csrf})
        empty_query = client.post(
            f"/ui/items/{item_id}/releases/search",
            data={"csrf": csrf, "query": "", "indexer": ""},
        )
        missing = client.post(
            "/ui/acquisitions/not-a-uuid/reconcile",
            data={"csrf": csrf},
        )

    assert legacy.status_code in {404, 405}
    assert empty_query.status_code == 422
    assert 'data-error-code="release_search_query_required"' in empty_query.text
    assert missing.status_code == 404
    assert 'data-error-code="acquisition_not_found"' in missing.text


def test_pending_system_reconcile_does_not_require_prowlarr(release_app) -> None:
    with TestClient(release_app) as client:
        csrf = _csrf(client.get("/").text)
        item_id, _ = _create_item_and_release(client, csrf)
        sessions = session_factory(release_app.state.engine)
        with sessions() as database:
            item = database.get(MediaItem, item_id)
            assert item is not None and item.current_revision_id is not None
            acquisition = Acquisition(
                media_item_id=item.id,
                metadata_revision_id=item.current_revision_id,
                download_client_instance_id=SYSTEM_QBITTORRENT_ID,
                idempotency_key="reconcile-without-prowlarr",
                naming_profile="jellyfin-v1",
                status="pending",
                destination="movies",
            )
            database.add(acquisition)
            database.commit()
            acquisition_identity = acquisition.id
        correlation = f"mf-acq-{acquisition_identity}"
        release_app.state.fake_client.tasks[correlation] = "movies"
        release_app.state.runtime._prowlarr = None

        reconciled = client.post(
            f"/ui/acquisitions/{acquisition_identity}/reconcile",
            data={"csrf": csrf},
            follow_redirects=False,
        )

    assert reconciled.status_code == 303
    with sessions() as database:
        stored = database.get(Acquisition, acquisition_identity)
    assert stored is not None and stored.status == "submitted"
