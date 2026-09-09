from fake_control_gateway import FakeControlGateway
from fastapi.testclient import TestClient
from media_finder_control.models import ReleaseSearchRequest, ReleaseSearchResult
from media_finder_server.control_api import create_control_app
from media_finder_server.control_security import BackendBrowserSecurity


class _PopulatedMetricsGateway(FakeControlGateway):
    async def search_releases(
        self,
        *,
        item_id: str,
        request: ReleaseSearchRequest,
    ) -> tuple[ReleaseSearchResult, ...]:
        del item_id, request
        return (
            ReleaseSearchResult(
                token="release-populated",
                title="Example.Release.1080p",
                indexer="Fixture Indexer",
                size=123456789,
                seeders=0,
            ),
        )


def test_release_acquisition_and_diagnostics_http_adapter_is_safe() -> None:
    with TestClient(
        create_control_app(
            gateway=FakeControlGateway(),
            security=BackendBrowserSecurity(secret=b"browser-session-secret-at-least-32-bytes"),
        )
    ) as client:
        session = client.get("/v1/session").json()
        headers = {
            "Origin": "http://testserver",
            "X-CSRF-Token": session["csrf_token"],
        }
        search = client.post(
            "/v1/media-items/movie-1/release-searches",
            json={"query": "Example", "indexer_ids": []},
            headers=headers,
        )
        assert search.status_code == 200
        assert search.json() == [
            {
                "token": "release-pending",
                "title": "Example.Release.1080p",
                "indexer": None,
                "size": None,
                "seeders": None,
            }
        ]
        assert "download_url" not in search.text
        assert "magnet" not in search.text

        destinations = client.get("/v1/download-destinations")
        assert destinations.status_code == 200
        assert destinations.json() == [{"key": "movies", "label": "Movies"}]

        submitted = client.post(
            "/v1/acquisitions",
            json={
                "media_item_id": "movie-1",
                "release_token": "release-pending",
                "destination": "movies",
                "idempotency_key": "browser-attempt-1",
            },
            headers=headers,
        )
        assert submitted.status_code == 201
        acquisition_id = submitted.json()["id"]
        assert submitted.json()["status"] == "pending"
        reconciled = client.post(
            f"/v1/acquisitions/{acquisition_id}/reconcile",
            json={},
            headers=headers,
        )
        assert reconciled.status_code == 200
        assert reconciled.json()["status"] == "submitted"

        diagnostics = client.get("/v1/integrations")
        assert diagnostics.status_code == 200
        assert {entry["key"] for entry in diagnostics.json()} == {"manual", "tmdb"}
        assert "secret-value" not in diagnostics.text.casefold()
        assert "base_url" not in diagnostics.text.casefold()

        about = client.get("/v1/about")
        assert about.status_code == 200
        assert about.json()["version"] == "0.1.0-dev"


def test_release_search_http_projects_populated_metrics_from_a_local_gateway() -> None:
    with TestClient(
        create_control_app(
            gateway=_PopulatedMetricsGateway(),
            security=BackendBrowserSecurity(secret=b"browser-session-secret-at-least-32-bytes"),
        )
    ) as client:
        session = client.get("/v1/session").json()
        response = client.post(
            "/v1/media-items/movie-1/release-searches",
            json={"query": "Example", "indexer_ids": []},
            headers={
                "Origin": "http://testserver",
                "X-CSRF-Token": session["csrf_token"],
            },
        )

    assert response.status_code == 200
    assert response.json() == [
        {
            "token": "release-populated",
            "title": "Example.Release.1080p",
            "indexer": "Fixture Indexer",
            "size": 123456789,
            "seeders": 0,
        }
    ]
