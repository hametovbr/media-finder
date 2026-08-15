import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from media_finder.db import migrate_to_head, session_factory
from media_finder.models import Acquisition, DownloadClientInstance
from media_finder.prowlarr import ProwlarrAdapter, SearchResultCache
from media_finder.sdk.types import CorrelationResult, DownloadDestination, SubmissionResult
from media_finder.ui import create_ui_app


def _csrf(text: str) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', text)
    assert match
    return match.group(1)


def _value(text: str, test_id: str) -> str:
    match = re.search(rf'data-testid="{test_id}"[\s\S]*?value="([^"]+)"', text)
    assert match
    return match.group(1)


class FakeProwlarrTransport:
    def search(self, query: str, filters: dict[str, str]) -> list[dict[str, object]]:
        return [
            {
                "protocol": "torrent",
                "title": query,
                "indexer": "Fixture Indexer",
                "magnetUrl": "magnet:?xt=urn:btih:0123456789012345678901234567890123456789",
            }
        ]

    def fetch_torrent(self, url: str) -> bytes:
        raise AssertionError("magnet result must not fetch torrent bytes")


class MutableClient:
    def __init__(self, destination: str) -> None:
        self.destinations = [DownloadDestination(key=destination, label=destination.upper())]
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
    clients = {"first": MutableClient("first"), "second": MutableClient("second")}
    app = create_ui_app(
        database_url,
        session_secret_reference="env:MEDIA_FINDER_UI_SECRET",
        prowlarr=ProwlarrAdapter(FakeProwlarrTransport(), SearchResultCache()),
        client_loader=lambda instance: clients[instance.name.casefold()],
    )
    sessions = session_factory(app.state.engine)
    with sessions() as database:
        first = DownloadClientInstance(name="First", module_key="fixture", config_payload={})
        second = DownloadClientInstance(name="Second", module_key="fixture", config_payload={})
        database.add_all([first, second])
        database.commit()
        app.state.client_ids = {"first": first.id, "second": second.id}
    app.state.fake_clients = clients
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


def test_selected_client_loads_its_live_destinations_and_initial_page_targets_query_endpoint(
    release_app,
) -> None:
    with TestClient(release_app) as client:
        csrf = _csrf(client.get("/").text)
        item_id, _ = _create_item_and_release(client, csrf)
        page = client.get(f"/items/{item_id}/releases")
        assert 'hx-post="/ui/clients/destinations"' in page.text
        assert 'hx-trigger="load, change"' in page.text

        second = client.post(
            "/ui/clients/destinations",
            data={
                "csrf": csrf,
                "client_instance_id": release_app.state.client_ids["second"],
            },
            headers={"HX-Request": "true"},
        )

    assert second.status_code == 200
    assert '<option value="second">SECOND</option>' in second.text
    assert '<option value="first">FIRST</option>' not in second.text


def test_destination_drift_returns_current_choices_and_keeps_release_token_reusable(
    release_app,
) -> None:
    with TestClient(release_app) as client:
        csrf = _csrf(client.get("/").text)
        item_id, release_token = _create_item_and_release(client, csrf)
        instance_id = release_app.state.client_ids["second"]
        release_app.state.fake_clients["second"].destinations = [
            DownloadDestination(key="current", label="CURRENT")
        ]
        payload = {
            "csrf": csrf,
            "release_token": release_token,
            "client_instance_id": instance_id,
            "destination": "stale",
            "idempotency_key": "drift-key",
        }

        drifted = client.post(f"/ui/items/{item_id}/acquisitions", data=payload)
        assert drifted.status_code == 409
        assert 'data-error-code="download_destination_unavailable"' in drifted.text
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
        assert attempts[0].status == "submitted"


def test_release_and_reconcile_domain_errors_keep_stable_codes_and_safe_messages(
    release_app,
) -> None:
    with TestClient(release_app, raise_server_exceptions=False) as client:
        csrf = _csrf(client.get("/").text)
        item_id, release_token = _create_item_and_release(client, csrf)
        empty_query = client.post(
            f"/ui/items/{item_id}/releases/search",
            data={"csrf": csrf, "query": "", "indexer": ""},
        )
        assert empty_query.status_code == 422
        assert 'data-error-code="release_search_query_required"' in empty_query.text
        assert "Enter a search query." in empty_query.text

        invalid_reference = client.post(
            f"/ui/items/{item_id}/acquisitions",
            data={
                "csrf": csrf,
                "release_token": release_token,
                "client_instance_id": "missing",
                "destination": "second",
                "idempotency_key": "invalid-reference",
            },
        )
        assert invalid_reference.status_code == 422
        assert 'data-error-code="acquisition_reference_not_found"' in invalid_reference.text

        missing = client.post(
            "/ui/acquisitions/not-a-uuid/reconcile",
            data={"csrf": csrf},
        )
        assert missing.status_code == 404
        assert 'data-error-code="acquisition_not_found"' in missing.text
