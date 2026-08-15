import re

from fastapi.testclient import TestClient
from media_finder_builtin_ui import create_builtin_ui
from media_finder_builtin_ui.fake import FakeBrowserSecurity, FakeControlGateway


def _csrf(html: str) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


def test_catalog_detail_and_mutations_use_only_the_fake_gateway() -> None:
    gateway = FakeControlGateway()
    with TestClient(create_builtin_ui(gateway=gateway, security=FakeBrowserSecurity())) as client:
        catalog = client.get("/")
        csrf = _csrf(catalog.text)
        assert "Example Movie" in catalog.text
        assert "Submitted" in catalog.text

        detail = client.get("/items/series-1")
        assert detail.status_code == 200
        assert "Example Series" in detail.text
        assert "Season 00" in detail.text
        assert "Special" in detail.text

        fragment = client.get("/ui/items/movie-1/tabs/acquisitions")
        assert fragment.status_code == 200
        assert fragment.headers["Vary"] == "HX-Request"
        assert "<html" not in fragment.text

        created = client.post(
            "/ui/collections",
            data={"csrf": csrf, "name": "Family"},
            follow_redirects=False,
        )
        assert created.status_code == 303
        archived = client.post(
            "/ui/items/movie-1/archive",
            data={"csrf": csrf},
            follow_redirects=False,
        )
        assert archived.status_code == 303
        moved = client.post(
            "/ui/items/movie-1/move",
            data={"csrf": csrf, "collection_id": "collection-1"},
            follow_redirects=False,
        )
        assert moved.status_code == 303

        denied = client.post("/ui/collections", data={"name": "No CSRF"})
        assert denied.status_code == 403
        assert "csrf_invalid" in denied.text


def test_ui_and_metadata_locale_remain_independent_in_the_signed_session() -> None:
    with TestClient(
        create_builtin_ui(
            gateway=FakeControlGateway(),
            security=FakeBrowserSecurity(),
        )
    ) as client:
        csrf = _csrf(client.get("/", headers={"Accept-Language": "ru"}).text)
        metadata = client.post(
            "/ui/metadata-locale",
            data={"csrf": csrf, "metadata_locale": "en"},
            follow_redirects=False,
        )
        assert metadata.status_code == 303
        changed = client.post(
            "/ui/locale",
            data={"csrf": csrf, "locale": "ru"},
            follow_redirects=False,
        )
        assert changed.status_code == 303
