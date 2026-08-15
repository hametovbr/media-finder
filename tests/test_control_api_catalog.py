from fastapi.testclient import TestClient
from media_finder_builtin_ui.fake import FakeControlGateway

from media_finder.control_api import create_control_app
from media_finder.control_security import BackendBrowserSecurity


def test_control_catalog_routes_match_gateway_resources_and_statuses() -> None:
    gateway = FakeControlGateway()
    with TestClient(
        create_control_app(
            gateway=gateway,
            security=BackendBrowserSecurity(secret=b"browser-session-secret-at-least-32-bytes"),
        )
    ) as client:
        session = client.get("/v1/session").json()
        headers = {
            "Origin": "http://testserver",
            "X-CSRF-Token": session["csrf_token"],
        }

        collections = client.get("/v1/collections")
        assert collections.status_code == 200
        assert collections.json()["items"][0]["name"] == "Examples"
        created = client.post("/v1/collections", json={"name": "New"}, headers=headers)
        assert created.status_code == 201
        assert created.json() == {"id": "collection-created", "name": "New", "archived": False}
        archived = client.patch(
            "/v1/collections/collection-1", json={"archived": True}, headers=headers
        )
        assert archived.status_code == 200
        assert archived.json()["archived"] is True

        catalog = client.get("/v1/media-items", params={"locale": "en", "limit": 1})
        assert catalog.status_code == 200
        assert catalog.json()["items"][0]["title"] == "Example Movie"
        detail = client.get("/v1/media-items/series-1", params={"locale": "en"})
        assert detail.status_code == 200
        assert detail.json()["metadata"]["seasons"][0]["number"] == 0
        changed = client.patch(
            "/v1/media-items/series-1",
            json={"operation": "move", "collection_id": "collection-1", "locale": "en"},
            headers=headers,
        )
        assert changed.status_code == 200
        assert changed.json()["collection_id"] == "collection-1"


def test_catalog_query_limits_and_patch_operations_are_validated() -> None:
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
        too_many = client.get("/v1/media-items", params={"limit": 101})
        assert too_many.status_code == 422
        assert too_many.json()["error"]["code"] == "request_invalid"
        invalid_move = client.patch(
            "/v1/media-items/series-1",
            json={"operation": "move", "locale": "en"},
            headers=headers,
        )
        assert invalid_move.status_code == 422
        assert invalid_move.json()["error"]["code"] == "request_invalid"
