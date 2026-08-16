from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from media_finder_core.platform.database import migrate_to_head
from media_finder_server import create_ui_app
from sqlalchemy import inspect


@pytest.fixture
def settings_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    url = f"sqlite:///{tmp_path / 'settings.db'}"
    migrate_to_head(url)
    monkeypatch.setenv("MEDIA_FINDER_UI_SECRET", "a sufficiently long test session secret")
    return url


def test_settings_lists_exact_missing_environment_without_values(settings_url: str) -> None:
    app = create_ui_app(
        settings_url,
        session_secret_reference="env:MEDIA_FINDER_UI_SECRET",
        environment={},
    )

    with TestClient(app) as client:
        page = client.get("/settings")

    assert page.status_code == 200
    for name in (
        "TMDB_TOKEN",
        "PROWLARR_URL",
        "PROWLARR_API_KEY",
        "QBITTORRENT_URL",
        "QBITTORRENT_USERNAME",
        "QBITTORRENT_PASSWORD",
    ):
        assert f'data-environment-variable="{name}"' in page.text
        assert f"<code>{name}</code>" in page.text
    assert page.text.count('data-variable-state="missing"') == 6
    assert 'data-integration-state="missing"' in page.text
    assert "a sufficiently long test session secret" not in page.text
    assert "/ui/settings/" not in page.text
    assert 'name="api_token"' not in page.text
    assert 'name="client_instance_id"' not in page.text


def test_settings_distinguishes_ready_from_unavailable_without_disclosure(
    settings_url: str,
) -> None:
    environment = {
        "TMDB_TOKEN": "tmdb-secret-never-render",
        "PROWLARR_URL": "https://prowlarr.example.test",
        "PROWLARR_API_KEY": "prowlarr-secret-never-render",
        "QBITTORRENT_URL": "https://qb.example.test",
        "QBITTORRENT_USERNAME": "qb-user-never-render",
        "QBITTORRENT_PASSWORD": "qb-password-never-render",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.themoviedb.org":
            return httpx.Response(200, json={})
        if request.url.host == "prowlarr.example.test":
            return httpx.Response(503, text="upstream-secret-body")
        if request.url.host == "qb.example.test":
            if request.url.path == "/api/v2/auth/login":
                return httpx.Response(200, text="Ok.")
            return httpx.Response(200, json={})
        return httpx.Response(404)

    app = create_ui_app(
        settings_url,
        session_secret_reference="env:MEDIA_FINDER_UI_SECRET",
        environment=environment,
        http_client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with TestClient(app) as client:
        page = client.get("/settings")

    assert 'data-integration="tmdb" data-integration-state="ready"' in page.text
    assert 'data-integration="prowlarr" data-integration-state="unavailable"' in page.text
    assert 'data-integration="qbittorrent" data-integration-state="ready"' in page.text
    assert page.text.count('data-variable-state="set"') == 6
    for value in environment.values():
        assert value not in page.text
    assert "upstream-secret-body" not in page.text


@pytest.mark.parametrize(
    "path",
    [
        "/ui/settings/providers/tmdb",
        "/ui/settings/prowlarr",
        "/ui/settings/clients",
        "/ui/settings/clients/legacy/archive",
        "/ui/settings/clients/legacy/restore",
    ],
)
def test_legacy_integration_mutation_routes_are_absent(settings_url: str, path: str) -> None:
    app = create_ui_app(
        settings_url,
        session_secret_reference="env:MEDIA_FINDER_UI_SECRET",
        environment={},
    )
    with TestClient(app) as client:
        response = client.post(path)

    assert response.status_code in {404, 405}
    tables = set(inspect(app.state.engine).get_table_names())
    assert "app_settings" not in tables
    assert "download_client_instances" not in tables
