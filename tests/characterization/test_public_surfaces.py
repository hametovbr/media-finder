"""Characterization seam for package movement without product behavior changes."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from media_finder.db import migrate_to_head
from media_finder.runtime import create_application


def _configure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    ui_mode: str,
) -> None:
    database_url = f"sqlite:///{tmp_path / f'{ui_mode}.db'}"
    monkeypatch.setenv("MEDIA_FINDER_DATABASE_URL", database_url)
    monkeypatch.setenv("MEDIA_FINDER_UI_SECRET", "a sufficiently long characterization secret")
    monkeypatch.setenv("MEDIA_FINDER_INTEGRATION_TOKEN", "characterization-token")
    monkeypatch.setenv("MEDIA_FINDER_SECURE_COOKIE", "false")
    monkeypatch.setenv("MEDIA_FINDER_UI_MODE", ui_mode)
    migrate_to_head(database_url)


def test_builtin_public_surfaces_preserve_routes_security_and_localization(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure(monkeypatch, tmp_path, ui_mode="builtin")

    with TestClient(create_application()) as client:
        catalog = client.get("/", headers={"Accept-Language": "ru-RU, en;q=0.8"})
        assert catalog.status_code == 200
        assert "Добавить тайтл" in catalog.text
        assert "mf_session=" in catalog.headers["set-cookie"]
        assert "HttpOnly" in catalog.headers["set-cookie"]
        assert "SameSite=lax" in catalog.headers["set-cookie"]

        session = client.get("/api/control/v1/session")
        assert session.status_code == 200
        csrf = session.json()["csrf_token"]
        assert session.json()["supported_locales"] == ["en", "ru"]

        diagnostics = client.get("/api/control/v1/integrations")
        assert diagnostics.status_code == 200
        assert {item["key"] for item in diagnostics.json()} >= {"manual", "tmdb"}

        rejected = client.post(
            "/api/control/v1/collections",
            headers={"Origin": "http://testserver", "Content-Type": "application/json"},
            json={"name": "Characterization"},
        )
        assert rejected.status_code == 403
        assert rejected.json()["error"]["code"] == "csrf_invalid"

        accepted = client.post(
            "/api/control/v1/collections",
            headers={
                "Origin": "http://testserver",
                "Content-Type": "application/json",
                "X-CSRF-Token": csrf,
            },
            json={"name": "Characterization"},
        )
        assert accepted.status_code == 201

        assert client.get("/api/control/openapi.json").status_code == 200
        assert client.get("/health/live").json() == {"status": "live"}
        assert client.get("/health/ready").status_code == 200

        unauthorized = client.get("/api/v1/media-items/missing/metadata")
        assert unauthorized.status_code == 401
        assert unauthorized.json()["error"]["code"] == "authentication_required"
        missing = client.get(
            "/api/v1/media-items/missing/metadata",
            headers={"Authorization": "Bearer characterization-token"},
        )
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "media_item_not_found"


def test_disabled_mode_removes_presentation_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _configure(monkeypatch, tmp_path, ui_mode="disabled")

    with TestClient(create_application()) as client:
        assert client.get("/").status_code == 404
        assert client.get("/static/base.css").status_code == 404
        assert client.get("/api/control/v1/session").status_code == 200
        assert client.get("/api/v1/media-items/missing/metadata").status_code == 401
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 200
