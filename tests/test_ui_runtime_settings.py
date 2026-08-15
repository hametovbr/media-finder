import json
import re
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from media_finder.db import migrate_to_head
from media_finder.models import DownloadClientInstance
from media_finder.modules.tmdb import TmdbProvider
from media_finder.prowlarr import ProwlarrAdapter, SearchResultCache
from media_finder.ui import create_ui_app
from media_finder.ui_runtime import DefaultRuntimeFactory, RuntimeResult


def _csrf(text: str) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', text)
    assert match
    return match.group(1)


class EmptyProwlarrTransport:
    def search(self, query: str, filters: dict[str, str]) -> list[dict[str, object]]:
        return []

    def fetch_torrent(self, url: str) -> bytes:
        return b""


class PersistedRuntimeFactory:
    def __init__(self, provider, client) -> None:
        self.provider = provider
        self.client = client
        self.provider_configs: list[dict[str, object]] = []
        self.prowlarr_configs: list[dict[str, object]] = []
        self.client_names: list[str] = []

    def metadata_provider(self, key: str, config):
        self.provider_configs.append(dict(config))
        if key == "tmdb" and config:
            return RuntimeResult(self.provider)
        return RuntimeResult(None, "metadata_provider_not_configured")

    def prowlarr(self, config):
        self.prowlarr_configs.append(dict(config))
        if config:
            return RuntimeResult(ProwlarrAdapter(EmptyProwlarrTransport(), SearchResultCache()))
        return RuntimeResult(None, "prowlarr_not_configured")

    def download_client(self, instance):
        self.client_names.append(instance.name)
        return RuntimeResult(self.client)


def test_persisted_settings_drive_readiness_and_runtime_resolution_after_save_and_rebuild(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_provider,
    fake_client,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'runtime-settings.db'}"
    migrate_to_head(database_url)
    monkeypatch.setenv("MEDIA_FINDER_UI_SECRET", "a sufficiently long test session secret")
    first_factory = PersistedRuntimeFactory(fake_provider, fake_client)
    app = create_ui_app(
        database_url,
        session_secret_reference="env:MEDIA_FINDER_UI_SECRET",
        providers={"tmdb": TmdbProvider.retention_only()},
        runtime_factory=first_factory,
    )

    with TestClient(app) as client:
        csrf = _csrf(client.get("/").text)
        before = client.get("/settings")
        assert 'data-readiness="tmdb:not-ready"' in before.text
        assert 'data-readiness="prowlarr:not-ready"' in before.text
        assert "Manual-only catalog use remains available." in before.text

        assert (
            client.post(
                "/ui/settings/providers/tmdb",
                data={
                    "csrf": csrf,
                    "api_token": "env:TMDB_API_TOKEN",
                    "base_url": "https://api.themoviedb.org/3",
                },
                follow_redirects=False,
            ).status_code
            == 303
        )
        assert (
            client.post(
                "/ui/settings/prowlarr",
                data={
                    "csrf": csrf,
                    "base_url": "https://prowlarr.example.test",
                    "api_key_ref": "env:PROWLARR_API_KEY",
                },
                follow_redirects=False,
            ).status_code
            == 303
        )
        assert (
            client.post(
                "/ui/settings/clients",
                data={
                    "csrf": csrf,
                    "name": "Runtime qB",
                    "module_key": "qbittorrent",
                    "base_url": "https://qb.example.test",
                    "username_ref": "env:QB_USERNAME",
                    "password_ref": "env:QB_PASSWORD",
                },
                follow_redirects=False,
            ).status_code
            == 303
        )

        after = client.get("/settings")
        assert 'data-readiness="tmdb:ready"' in after.text
        assert 'data-readiness="prowlarr:ready"' in after.text
        assert 'data-readiness="client:ready"' in after.text
        search = client.post(
            "/ui/metadata/search",
            data={"csrf": csrf, "query": "Configured", "metadata_locale": "en"},
            headers={"HX-Request": "true"},
        )
        assert 'data-testid="provider-results-tmdb"' in search.text
        assert "Configured" in search.text

    second_factory = PersistedRuntimeFactory(fake_provider, fake_client)
    rebuilt = create_ui_app(
        database_url,
        session_secret_reference="env:MEDIA_FINDER_UI_SECRET",
        providers={"tmdb": TmdbProvider.retention_only()},
        runtime_factory=second_factory,
    )
    with TestClient(rebuilt) as client:
        readiness = client.get("/settings")
        assert 'data-readiness="tmdb:ready"' in readiness.text
        assert 'data-readiness="prowlarr:ready"' in readiness.text
        assert 'data-readiness="client:ready"' in readiness.text

    assert first_factory.provider_configs
    assert first_factory.prowlarr_configs
    assert first_factory.client_names == ["Runtime qB"]
    assert second_factory.provider_configs
    assert second_factory.prowlarr_configs
    assert second_factory.client_names == ["Runtime qB"]


def test_generic_settings_render_typed_provider_and_download_client_schemas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'generic-settings.db'}"
    migrate_to_head(database_url)
    monkeypatch.setenv("MEDIA_FINDER_UI_SECRET", "a sufficiently long test session secret")
    app = create_ui_app(
        database_url,
        session_secret_reference="env:MEDIA_FINDER_UI_SECRET",
        providers={"tmdb": TmdbProvider.retention_only()},
    )

    with TestClient(app) as client:
        page = client.get("/settings")

    assert 'data-testid="module-settings-tmdb"' in page.text
    assert 'data-testid="client-module-qbittorrent"' in page.text
    assert 'name="module_key" value="qbittorrent"' in page.text
    assert 'name="username_ref"' in page.text
    assert 'name="password_ref"' in page.text
    assert "module.qbittorrent.username_ref" not in page.text


def test_default_runtime_reconstructs_persisted_integrations_across_apps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = f"sqlite:///{tmp_path / 'default-runtime.db'}"
    migrate_to_head(database_url)
    monkeypatch.setenv("MEDIA_FINDER_UI_SECRET", "a sufficiently long test session secret")
    monkeypatch.setenv("TMDB_API_TOKEN", "tmdb-secret")
    monkeypatch.setenv("PROWLARR_API_KEY", "prowlarr-secret")
    monkeypatch.setenv("QB_USERNAME", "qb-user")
    monkeypatch.setenv("QB_PASSWORD", "qb-password")
    requests: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.url.host == "api.themoviedb.org":
            assert request.headers.get("Authorization") == "Bearer tmdb-secret"
            if request.url.path.endswith("/configuration"):
                return httpx.Response(200, json={})
            if request.url.path.endswith("/search/movie"):
                return httpx.Response(200, json={"results": []})
            if request.url.path.endswith("/search/tv"):
                return httpx.Response(200, json={"results": []})
        if request.url.host == "prowlarr.example.test":
            assert request.headers.get("X-Api-Key") == "prowlarr-secret"
            if request.url.path == "/api/v1/system/status":
                return httpx.Response(200, json={"version": "1"})
            if request.url.path == "/api/v1/search":
                return httpx.Response(
                    200,
                    json=[
                        {
                            "protocol": "torrent",
                            "title": "Persisted release",
                            "indexer": "Fixture",
                            "magnetUrl": (
                                "magnet:?xt=urn:btih:0123456789012345678901234567890123456789"
                            ),
                        }
                    ],
                )
        if request.url.host == "qb.example.test":
            if request.url.path == "/api/v2/auth/login":
                return httpx.Response(200, text="Ok.")
            if request.url.path == "/api/v2/torrents/categories":
                return httpx.Response(200, json={"movies": {"savePath": "/movies"}})
            if request.url.path == "/api/v2/torrents/add":
                return httpx.Response(200, text="Ok.")
        return httpx.Response(404)

    def http_client_factory() -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler))

    first = create_ui_app(
        database_url,
        session_secret_reference="env:MEDIA_FINDER_UI_SECRET",
        http_client_factory=http_client_factory,
    )
    with TestClient(first) as client:
        csrf = _csrf(client.get("/").text)
        about = client.get("/about")
        assert "User-provided metadata" in about.text
        assert "This product uses the TMDB API" not in about.text
        for path, data in (
            (
                "/ui/settings/providers/tmdb",
                {
                    "csrf": csrf,
                    "api_token": "env:TMDB_API_TOKEN",
                    "base_url": "https://api.themoviedb.org/3",
                },
            ),
            (
                "/ui/settings/prowlarr",
                {
                    "csrf": csrf,
                    "base_url": "https://prowlarr.example.test",
                    "api_key_ref": "env:PROWLARR_API_KEY",
                },
            ),
            (
                "/ui/settings/clients",
                {
                    "csrf": csrf,
                    "name": "Persisted qB",
                    "module_key": "qbittorrent",
                    "base_url": "https://qb.example.test",
                    "username_ref": "env:QB_USERNAME",
                    "password_ref": "env:QB_PASSWORD",
                },
            ),
        ):
            assert client.post(path, data=data, follow_redirects=False).status_code == 303
        readiness = client.get("/settings")
        assert 'data-readiness="tmdb:ready"' in readiness.text
        assert 'data-readiness="prowlarr:ready"' in readiness.text
        assert 'data-readiness="client:ready"' in readiness.text
        assert "This product uses the TMDB API" in client.get("/about").text

        created = client.post(
            "/ui/manual/import",
            data={
                "csrf": csrf,
                "document": json.dumps(
                    {
                        "schema_version": "1",
                        "kind": "movie",
                        "locale": "en",
                        "titles": {"en": "Persisted"},
                    }
                ),
            },
            follow_redirects=False,
        )
        item_id = created.headers["location"].split("/")[2].split("?")[0]
        searched = client.post(
            f"/ui/items/{item_id}/releases/search",
            data={"csrf": csrf, "query": "Persisted", "indexer": ""},
        )
        release_token = re.search(r'value="([^"]+)" required', searched.text)
        assert release_token
        settings = first.state.sessions()
        with settings as database:
            instance_id = database.scalar(
                select(DownloadClientInstance.id).where(
                    DownloadClientInstance.name == "Persisted qB"
                )
            )
        submitted = client.post(
            f"/ui/items/{item_id}/acquisitions",
            data={
                "csrf": csrf,
                "release_token": release_token.group(1),
                "client_instance_id": instance_id,
                "destination": "movies",
                "idempotency_key": "default-runtime-submit",
            },
            follow_redirects=False,
        )
        assert submitted.status_code == 303

    rebuilt = create_ui_app(
        database_url,
        session_secret_reference="env:MEDIA_FINDER_UI_SECRET",
        http_client_factory=http_client_factory,
    )
    with TestClient(rebuilt) as client:
        page = client.get("/settings")
        assert 'data-readiness="tmdb:ready"' in page.text
        assert 'data-readiness="prowlarr:ready"' in page.text
        assert 'data-readiness="client:ready"' in page.text

    assert ("GET", "/api/v1/system/status") in requests
    assert ("POST", "/api/v2/torrents/add") in requests


def test_default_factory_returns_safe_codes_for_invalid_or_unknown_modules() -> None:
    factory = DefaultRuntimeFactory(
        http_client_factory=lambda: httpx.Client(transport=httpx.MockTransport(lambda _: None))
    )
    assert factory.metadata_provider("unknown", {}).error_code == "metadata_provider_not_found"
    assert factory.prowlarr({"base_url": "not-a-url"}).error_code == (
        "prowlarr_configuration_invalid"
    )


def test_about_keeps_configured_tmdb_attribution_during_live_outage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = f"sqlite:///{tmp_path / 'tmdb-outage.db'}"
    migrate_to_head(database_url)
    monkeypatch.setenv("MEDIA_FINDER_UI_SECRET", "a sufficiently long test session secret")
    monkeypatch.setenv("TMDB_API_TOKEN", "tmdb-secret")

    def failing_client() -> httpx.Client:
        def timeout(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("upstream unavailable", request=request)

        return httpx.Client(transport=httpx.MockTransport(timeout))

    app = create_ui_app(
        database_url,
        session_secret_reference="env:MEDIA_FINDER_UI_SECRET",
        http_client_factory=failing_client,
    )
    with TestClient(app) as client:
        csrf = _csrf(client.get("/").text)
        saved = client.post(
            "/ui/settings/providers/tmdb",
            data={
                "csrf": csrf,
                "api_token": "env:TMDB_API_TOKEN",
                "base_url": "https://api.themoviedb.org/3",
            },
            follow_redirects=False,
        )
        assert saved.status_code == 303

        readiness = client.get("/settings")
        assert 'data-readiness="tmdb:not-ready"' in readiness.text
        about = client.get("/about")

    assert "User-provided metadata" in about.text
    assert "This product uses the TMDB API but is not endorsed or certified by TMDB." in (
        about.text
    )
