from collections.abc import Callable, Mapping
from pathlib import Path

import httpx
from fastapi.testclient import TestClient
from media_finder_core.platform.database import migrate_to_head
from media_finder_server import create_application
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


def _application(
    database_url: str,
    *,
    module_environment: Mapping[str, str],
    client_factory: Callable[[], httpx.Client],
):
    return create_application(
        environment={
            "MEDIA_FINDER_DATABASE_URL": database_url,
            "MEDIA_FINDER_UI_SECRET": "a sufficiently long test session secret",
            "MEDIA_FINDER_INTEGRATION_TOKEN": "integration-token",
            "MEDIA_FINDER_SECURE_COOKIE": "false",
            "MEDIA_FINDER_UI_MODE": "builtin",
            **module_environment,
        },
        http_client_factory=client_factory,
    )


def test_environment_runtime_is_reconstructed_without_persisted_settings(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'runtime.db'}"
    migrate_to_head(url)

    def create():
        return _application(
            url,
            module_environment=ENVIRONMENT,
            client_factory=lambda: httpx.Client(transport=httpx.MockTransport(_handler)),
        )

    for application in (create(), create()):
        with TestClient(application) as client:
            settings = client.get("/settings")
            about = client.get("/about")
            tables = set(inspect(application.state.engine).get_table_names())
        assert 'data-integration="tmdb" data-integration-state="ready"' in settings.text
        assert 'data-integration="prowlarr" data-integration-state="ready"' in settings.text
        assert 'data-integration="qbittorrent" data-integration-state="ready"' in settings.text
        assert "This product uses the TMDB API" in about.text
        for value in ENVIRONMENT.values():
            assert value not in settings.text
        assert "app_settings" not in tables
        assert "download_client_instances" not in tables


def test_about_keeps_tmdb_attribution_during_live_outage(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'tmdb-outage.db'}"
    migrate_to_head(url)

    def failing_client() -> httpx.Client:
        def timeout(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("upstream unavailable", request=request)

        return httpx.Client(transport=httpx.MockTransport(timeout))

    application = _application(
        url,
        module_environment={"TMDB_TOKEN": "never-render-this-token"},
        client_factory=failing_client,
    )
    with TestClient(application) as client:
        readiness = client.get("/settings")
        about = client.get("/about")

    assert 'data-integration="tmdb" data-integration-state="unavailable"' in readiness.text
    assert "never-render-this-token" not in readiness.text
    assert "This product uses the TMDB API but is not endorsed or certified by TMDB." in (
        about.text
    )


def test_prowlarr_outage_is_reported_without_affecting_readiness(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'prowlarr-outage.db'}"
    migrate_to_head(url)

    def client_factory() -> httpx.Client:
        def prowlarr_outage(request: httpx.Request) -> httpx.Response:
            if request.url.host == "prowlarr.example.test":
                raise httpx.ReadTimeout("upstream unavailable", request=request)
            return _handler(request)

        return httpx.Client(transport=httpx.MockTransport(prowlarr_outage))

    application = _application(
        url,
        module_environment=ENVIRONMENT,
        client_factory=client_factory,
    )
    with TestClient(application) as client:
        ready = client.get("/health/ready")
        settings = client.get("/settings")

    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}
    assert 'data-integration="prowlarr" data-integration-state="unavailable"' in settings.text


def test_about_uses_environment_presence_with_root_owned_maintenance(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'about-no-probe.db'}"
    migrate_to_head(url)

    def record(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    application = _application(
        url,
        module_environment={"TMDB_TOKEN": "never-render-this-token"},
        client_factory=lambda: httpx.Client(transport=httpx.MockTransport(record)),
    )
    with TestClient(application) as client:
        about = client.get("/about")

    assert "This product uses the TMDB API but is not endorsed or certified by TMDB." in (
        about.text
    )
