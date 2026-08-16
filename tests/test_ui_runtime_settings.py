from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from media_finder_core.platform.database import migrate_to_head
from media_finder_server import create_runtime_factory, create_ui_app
from sqlalchemy import inspect

ENVIRONMENT = {
    "TMDB_TOKEN": "tmdb-secret",
    "PROWLARR_URL": "https://prowlarr.example.test",
    "PROWLARR_API_KEY": "prowlarr-secret",
    "QBITTORRENT_URL": "https://qb.example.test",
    "QBITTORRENT_USERNAME": "qb-user",
    "QBITTORRENT_PASSWORD": "qb-password",
}


def _handler(request: httpx.Request) -> httpx.Response:
    if request.url.host == "api.themoviedb.org":
        return httpx.Response(200, json={})
    if request.url.host == "prowlarr.example.test":
        return httpx.Response(200, json={"version": "1"})
    if request.url.host == "qb.example.test":
        if request.url.path == "/api/v2/auth/login":
            return httpx.Response(200, text="Ok.")
        if request.url.path == "/api/v2/torrents/categories":
            return httpx.Response(200, json={"movies": {"savePath": "/movies"}})
        return httpx.Response(200, json={})
    return httpx.Response(404)


def test_environment_runtime_is_reconstructed_without_persisted_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = f"sqlite:///{tmp_path / 'runtime.db'}"
    migrate_to_head(url)
    monkeypatch.setenv("MEDIA_FINDER_UI_SECRET", "a sufficiently long test session secret")

    def create():
        return create_ui_app(
            url,
            session_secret_reference="env:MEDIA_FINDER_UI_SECRET",
            environment=ENVIRONMENT,
            http_client_factory=lambda: httpx.Client(transport=httpx.MockTransport(_handler)),
        )

    for app in (create(), create()):
        with TestClient(app) as client:
            settings = client.get("/settings")
            about = client.get("/about")
        assert 'data-integration="tmdb" data-integration-state="ready"' in settings.text
        assert 'data-integration="prowlarr" data-integration-state="ready"' in settings.text
        assert 'data-integration="qbittorrent" data-integration-state="ready"' in settings.text
        assert "This product uses the TMDB API" in about.text
        for value in ENVIRONMENT.values():
            assert value not in settings.text
        tables = set(inspect(app.state.engine).get_table_names())
        assert "app_settings" not in tables
        assert "download_client_instances" not in tables


def test_default_factory_returns_safe_codes_for_missing_or_unknown_integrations() -> None:
    factory = create_runtime_factory(environment={})

    assert factory.metadata_provider("unknown").error_code == "metadata_provider_not_found"
    assert factory.release_selections().error_code == "module_environment_missing"


def test_about_keeps_tmdb_attribution_during_live_outage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = f"sqlite:///{tmp_path / 'tmdb-outage.db'}"
    migrate_to_head(url)
    monkeypatch.setenv("MEDIA_FINDER_UI_SECRET", "a sufficiently long test session secret")

    def failing_client() -> httpx.Client:
        def timeout(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("upstream unavailable", request=request)

        return httpx.Client(transport=httpx.MockTransport(timeout))

    app = create_ui_app(
        url,
        session_secret_reference="env:MEDIA_FINDER_UI_SECRET",
        environment={"TMDB_TOKEN": "never-render-this-token"},
        http_client_factory=failing_client,
    )
    with TestClient(app) as client:
        readiness = client.get("/settings")
        about = client.get("/about")

    assert 'data-integration="tmdb" data-integration-state="unavailable"' in readiness.text
    assert "never-render-this-token" not in readiness.text
    assert "This product uses the TMDB API but is not endorsed or certified by TMDB." in (
        about.text
    )


def test_about_uses_environment_presence_without_live_provider_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = f"sqlite:///{tmp_path / 'about-no-probe.db'}"
    migrate_to_head(url)
    monkeypatch.setenv("MEDIA_FINDER_UI_SECRET", "a sufficiently long test session secret")
    requests: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={})

    app = create_ui_app(
        url,
        session_secret_reference="env:MEDIA_FINDER_UI_SECRET",
        environment={"TMDB_TOKEN": "never-render-this-token"},
        http_client_factory=lambda: httpx.Client(transport=httpx.MockTransport(record)),
    )
    with TestClient(app) as client:
        about = client.get("/about")

    assert "This product uses the TMDB API but is not endorsed or certified by TMDB." in (
        about.text
    )
    assert requests == []
