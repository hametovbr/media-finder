from fastapi.testclient import TestClient
from media_finder_builtin_ui import create_builtin_ui
from media_finder_builtin_ui.fake import FakeBrowserSecurity, FakeControlGateway


def test_builtin_ui_preserves_public_html_route_inventory_with_fake_ports() -> None:
    app = create_builtin_ui(
        gateway=FakeControlGateway(),
        security=FakeBrowserSecurity(),
    )
    inventory = {
        (method, route.path) for route in app.routes for method in getattr(route, "methods", set())
    }
    assert {
        ("GET", "/"),
        ("GET", "/about"),
        ("GET", "/add"),
        ("GET", "/add/manual"),
        ("GET", "/items/{item_id}"),
        ("GET", "/items/{item_id}/edit"),
        ("GET", "/items/{item_id}/releases"),
        ("GET", "/settings"),
        ("GET", "/ui/items/{item_id}/tabs/acquisitions"),
        ("POST", "/ui/acquisitions/{acquisition_id}/reconcile"),
        ("POST", "/ui/collections"),
        ("POST", "/ui/collections/{collection_id}/archive"),
        ("POST", "/ui/collections/{collection_id}/restore"),
        ("POST", "/ui/items/{item_id}/acquisitions"),
        ("POST", "/ui/items/{item_id}/archive"),
        ("POST", "/ui/items/{item_id}/manual/csv"),
        ("POST", "/ui/items/{item_id}/move"),
        ("POST", "/ui/items/{item_id}/releases/search"),
        ("POST", "/ui/items/{item_id}/restore"),
        ("POST", "/ui/locale"),
        ("POST", "/ui/manual/confirm"),
        ("POST", "/ui/manual/import"),
        ("POST", "/ui/manual/save"),
        ("POST", "/ui/metadata-locale"),
        ("POST", "/ui/metadata/confirm"),
        ("POST", "/ui/metadata/search"),
        ("POST", "/ui/qbittorrent/destinations"),
    } <= inventory

    with TestClient(app) as client:
        catalog = client.get("/")
    assert catalog.status_code == 200
    assert "Example Movie" in catalog.text
    assert "mf_session=" in catalog.headers["set-cookie"]
    assert "HttpOnly" in catalog.headers["set-cookie"]
    assert "SameSite=lax" in catalog.headers["set-cookie"]
