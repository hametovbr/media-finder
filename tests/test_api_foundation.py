from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from media_finder.api import APIError, create_app
from media_finder.db import migrate_to_head


def test_health_is_public_and_readiness_requires_alembic_head(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MEDIA_FINDER_INTEGRATION_TOKEN", "correct horse")
    database_url = f"sqlite:///{tmp_path / 'health.db'}"
    client = TestClient(
        create_app(database_url, integration_token_reference="env:MEDIA_FINDER_INTEGRATION_TOKEN")
    )

    assert client.get("/health/live").json() == {"status": "live"}
    unavailable = client.get("/health/ready")
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "database_not_ready"

    migrate_to_head(database_url)
    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}


def test_api_auth_uses_constant_time_comparison_and_safe_error_envelope(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("MEDIA_FINDER_INTEGRATION_TOKEN", "correct horse")
    database_url = f"sqlite:///{tmp_path / 'auth.db'}"
    migrate_to_head(database_url)
    client = TestClient(
        create_app(database_url, integration_token_reference="env:MEDIA_FINDER_INTEGRATION_TOKEN")
    )

    missing = client.get("/api/v1/media-items/not-present/metadata")
    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert missing.json() == {
        "error": {
            "code": "authentication_required",
            "request_id": missing.headers["x-request-id"],
            "details": {},
        }
    }
    assert "correct horse" not in missing.text

    with patch(
        "media_finder.api.hmac.compare_digest", wraps=__import__("hmac").compare_digest
    ) as compared:
        denied = client.get(
            "/api/v1/media-items/not-present/metadata",
            headers={"Authorization": "Bearer wrong"},
        )
    assert denied.status_code == 401
    compared.assert_called_once()
    assert "correct horse" not in denied.text


def test_request_id_is_propagated_and_validation_details_are_allowlisted(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("MEDIA_FINDER_INTEGRATION_TOKEN", "token")
    database_url = f"sqlite:///{tmp_path / 'request-id.db'}"
    migrate_to_head(database_url)
    client = TestClient(
        create_app(database_url, integration_token_reference="env:MEDIA_FINDER_INTEGRATION_TOKEN")
    )
    headers = {"Authorization": "Bearer token", "X-Request-ID": "support-123"}

    response = client.get(
        "/api/v1/media-items/not-present/exports/naming",
        headers=headers,
        params={"entity_type": "invalid"},
    )

    assert response.status_code == 422
    assert response.headers["x-request-id"] == "support-123"
    error = response.json()["error"]
    assert error["code"] == "request_validation_failed"
    assert error["request_id"] == "support-123"
    assert set(error["details"]) == {"issues"}
    assert set(error["details"]["issues"][0]) <= {"field", "type"}


def test_not_found_conflict_and_internal_errors_share_safe_envelope(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("MEDIA_FINDER_INTEGRATION_TOKEN", "token")
    database_url = f"sqlite:///{tmp_path / 'errors.db'}"
    migrate_to_head(database_url)
    app = create_app(database_url, integration_token_reference="env:MEDIA_FINDER_INTEGRATION_TOKEN")

    @app.get("/test/conflict")
    def conflict() -> None:
        raise APIError(409, "acquisition_conflict", details={"reason": "already_pending"})

    @app.get("/test/internal")
    def internal() -> None:
        raise RuntimeError("SECRET https://user:pass@example.test/private?token=SECRET")

    client = TestClient(app, raise_server_exceptions=False)
    headers = {"Authorization": "Bearer token"}
    not_found = client.get("/api/v1/media-items/missing/metadata", headers=headers)
    conflict_response = client.get("/test/conflict")
    internal_response = client.get("/test/internal")

    assert not_found.status_code == 404
    assert not_found.json()["error"]["code"] == "media_item_not_found"
    assert conflict_response.status_code == 409
    assert conflict_response.json()["error"]["code"] == "acquisition_conflict"
    assert conflict_response.json()["error"]["details"] == {"reason": "already_pending"}
    assert internal_response.status_code == 500
    assert internal_response.json()["error"]["code"] == "internal_error"
    assert "SECRET" not in internal_response.text
    assert "example.test" not in internal_response.text
