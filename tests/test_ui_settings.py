import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from media_finder.db import migrate_to_head, session_factory
from media_finder.models import AppSetting, DownloadClientInstance
from media_finder.modules.tmdb import TmdbProvider
from media_finder.ui import create_ui_app


def _csrf(text: str) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', text)
    assert match
    return match.group(1)


@pytest.fixture
def settings_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    url = f"sqlite:///{tmp_path / 'settings.db'}"
    migrate_to_head(url)
    monkeypatch.setenv("MEDIA_FINDER_UI_SECRET", "a sufficiently long test session secret")
    return create_ui_app(
        url,
        session_secret_reference="env:MEDIA_FINDER_UI_SECRET",
        providers={"tmdb": TmdbProvider.retention_only()},
    )


def test_generic_settings_store_only_environment_references_and_safe_values(settings_app) -> None:
    with TestClient(settings_app) as client:
        csrf = _csrf(client.get("/").text)
        rejected = client.post(
            "/ui/settings/providers/tmdb",
            data={
                "csrf": csrf,
                "api_token": "literal-secret",
                "base_url": "https://api.themoviedb.org/3",
            },
        )
        assert rejected.status_code == 422

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

        prowlarr = client.post(
            "/ui/settings/prowlarr",
            data={
                "csrf": csrf,
                "base_url": "https://prowlarr.example.test",
                "api_key_ref": "env:PROWLARR_API_KEY",
            },
            follow_redirects=False,
        )
        assert prowlarr.status_code == 303

        download_client = client.post(
            "/ui/settings/clients",
            data={
                "csrf": csrf,
                "name": "Home",
                "module_key": "qbittorrent",
                "base_url": "https://qb.example.test",
                "username_ref": "env:QB_USERNAME",
                "password_ref": "env:QB_PASSWORD",
            },
            follow_redirects=False,
        )
        assert download_client.status_code == 303
        refreshed = client.get("/settings")
        assert "Ready: TMDB" in refreshed.text

    sessions = session_factory(settings_app.state.engine)
    with sessions() as session:
        tmdb = session.get(AppSetting, "metadata_provider:tmdb")
        assert tmdb is not None
        assert tmdb.value_payload["api_token"]["value"] == "env:TMDB_API_TOKEN"
        assert "literal-secret" not in str(tmdb.value_payload)
        configured_prowlarr = session.get(AppSetting, "prowlarr")
        assert configured_prowlarr is not None
        assert configured_prowlarr.value_payload["api_key_ref"] == "env:PROWLARR_API_KEY"
        instance = session.scalar(
            select(DownloadClientInstance).where(DownloadClientInstance.name == "Home")
        )
        assert instance is not None
        assert instance.config_payload["password_ref"] == "env:QB_PASSWORD"
