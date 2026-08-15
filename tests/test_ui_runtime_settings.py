import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from media_finder.db import migrate_to_head
from media_finder.modules.tmdb import TmdbProvider
from media_finder.prowlarr import ProwlarrAdapter, SearchResultCache
from media_finder.ui import create_ui_app
from media_finder.ui_runtime import RuntimeResult


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
