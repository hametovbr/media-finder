# ruff: noqa: RUF001
import json
import re

from fastapi.testclient import TestClient
from media_finder_builtin_ui import create_builtin_ui
from media_finder_builtin_ui.fake import FakeBrowserSecurity, FakeControlGateway


def _csrf(html: str) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


def _client() -> TestClient:
    return TestClient(
        create_builtin_ui(gateway=FakeControlGateway(), security=FakeBrowserSecurity())
    )


def test_public_html_routes_and_browser_cookie_remain_stable() -> None:
    app = create_builtin_ui(gateway=FakeControlGateway(), security=FakeBrowserSecurity())
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


def test_catalog_forms_fragments_locales_and_semantic_feedback_use_fake_ports() -> None:
    with _client() as client:
        catalog = client.get("/")
        csrf = _csrf(catalog.text)
        assert "Example Movie" in catalog.text
        assert "Submitted" in catalog.text

        detail = client.get("/items/series-1")
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
        assert (
            client.post(
                "/ui/items/movie-1/archive",
                data={"csrf": csrf},
                follow_redirects=False,
            ).status_code
            == 303
        )
        assert (
            client.post(
                "/ui/items/movie-1/move",
                data={"csrf": csrf, "collection_id": "collection-1"},
                follow_redirects=False,
            ).status_code
            == 303
        )
        assert client.post("/ui/collections", data={"name": "No CSRF"}).status_code == 403

        metadata_locale = client.post(
            "/ui/metadata-locale",
            data={"csrf": csrf, "metadata_locale": "en"},
            follow_redirects=False,
        )
        assert metadata_locale.status_code == 303
        ui_locale = client.post(
            "/ui/locale",
            data={"csrf": csrf, "locale": "ru"},
            follow_redirects=False,
        )
        assert ui_locale.status_code == 303
        assert "Пример фильма" in client.get("/").text

        for query, expected in (
            ("saved=1", "Тайтл сохранён."),
            ("duplicate=1", "Этот тайтл уже существует."),
            ("acquisition=pending", "Ожидает отправки"),
            ("reconciled=failed", "Не удалось отправить"),
        ):
            feedback = client.get(f"/items/movie-1?{query}")
            assert 'role="status"' in feedback.text
            assert 'aria-live="polite"' in feedback.text
            assert "data-autofocus" in feedback.text
            assert expected in feedback.text


def test_metadata_manual_and_acquisition_forms_use_only_fake_gateway() -> None:
    with _client() as client:
        add = client.get("/add")
        csrf = _csrf(add.text)
        search = client.post(
            "/ui/metadata/search",
            data={"csrf": csrf, "query": "Example"},
        )
        assert search.status_code == 200
        assert 'data-testid="provider-results-tmdb"' in search.text
        selected = client.post(
            "/ui/metadata/confirm",
            data={"csrf": csrf, "selection_token": "metadata-1"},
            follow_redirects=False,
        )
        assert selected.status_code == 303
        assert selected.headers["location"].startswith("/items/series-1")

        editor = client.get("/add/manual")
        assert 'data-testid="manual-structured-form"' in editor.text
        existing_editor = client.get("/items/movie-1/edit")
        assert 'value="e0a465bb-34eb-4565-bde2-b80d6e789b7c"' in existing_editor.text
        assert 'value="Example Movie"' in existing_editor.text
        assert (
            client.post(
                "/ui/manual/save",
                data={
                    "csrf": csrf,
                    "kind": "movie",
                    "metadata_locale": "en",
                    "title": "Local Movie",
                },
                follow_redirects=False,
            ).status_code
            == 303
        )
        warning = client.post(
            "/ui/manual/import",
            data={
                "csrf": csrf,
                "document": json.dumps(
                    {
                        "schema_version": "1",
                        "external_id": "e0a465bb-34eb-4565-bde2-b80d6e789b7c",
                        "kind": "movie",
                        "locale": "en",
                        "titles": {"en": "Updated"},
                    }
                ),
            },
        )
        token = re.search(r'name="draft_token" value="([^"]+)"', warning.text)
        assert token is not None
        assert (
            client.post(
                "/ui/manual/confirm",
                data={"csrf": csrf, "draft_token": token.group(1)},
                follow_redirects=False,
            ).status_code
            == 303
        )
        assert (
            client.post(
                "/ui/items/series-1/manual/csv",
                data={"csrf": csrf, "content": "season,episode,title\n1,1,Pilot\n"},
                follow_redirects=False,
            ).status_code
            == 303
        )

        release = client.get("/items/movie-1/releases")
        release_csrf = _csrf(release.text)
        results = client.post(
            "/ui/items/movie-1/releases/search",
            data={"csrf": release_csrf, "query": "Example"},
        )
        assert "Example.Release.1080p" in results.text
        destinations = client.post(
            "/ui/qbittorrent/destinations",
            data={"csrf": release_csrf},
        )
        assert "Movies" in destinations.text
        submitted = client.post(
            "/ui/items/movie-1/acquisitions",
            data={
                "csrf": release_csrf,
                "release_token": "release-pending",
                "destination": "movies",
                "idempotency_key": "ui-attempt-1",
            },
            follow_redirects=False,
        )
        assert submitted.status_code == 303
        reconciled = client.post(
            "/ui/acquisitions/movie-1-acquisition/reconcile",
            data={"csrf": release_csrf},
            follow_redirects=False,
        )
        assert reconciled.status_code == 303

        settings = client.get("/settings")
        assert "MEDIA_FINDER_TMDB_API_TOKEN" in settings.text
        assert "secret-value" not in settings.text
        assert "User-provided metadata" in client.get("/about").text
