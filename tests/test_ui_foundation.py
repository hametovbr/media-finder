import asyncio
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from media_finder.ui import error_message, resolve_locale
from media_finder_builtin_ui.forms import decode_form
from media_finder_core.platform.database import migrate_to_head
from media_finder_server import create_ui_app
from starlette.requests import Request

MAX_UI_FORM_BYTES = 1024 * 1024


def test_locale_resolution_prefers_signed_override_then_browser_language() -> None:
    assert resolve_locale("ru", "en-US,en;q=0.9") == "ru"
    assert resolve_locale(None, "ru-RU,ru;q=0.9,en;q=0.8") == "ru"
    assert resolve_locale(None, "de-DE,de;q=0.9") == "en"


def test_error_messages_are_localized_without_translating_machine_code() -> None:
    assert error_message("release_search_token_expired", "en") == (
        "The release selection expired. Search again.",
        "release_search_token_expired",
    )
    assert error_message("release_search_token_expired", "ru") == (
        "Срок действия выбранного релиза истёк. Выполните поиск снова.",
        "release_search_token_expired",
    )
    assert error_message("future_error", "ru") == (
        "Произошла безопасно скрытая ошибка.",
        "future_error",
    )


def test_ui_cookie_is_hardened_and_mutations_require_session_csrf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = f"sqlite:///{tmp_path / 'ui.db'}"
    migrate_to_head(database_url)
    monkeypatch.setenv("MEDIA_FINDER_UI_SECRET", "a sufficiently long test session secret")
    app = create_ui_app(
        database_url,
        session_secret_reference="env:MEDIA_FINDER_UI_SECRET",
        secure_cookie=True,
    )

    with TestClient(app) as client:
        page = client.get("/")
        cookie = page.headers["set-cookie"]
        assert "HttpOnly" in cookie
        assert "SameSite=lax" in cookie
        assert "Secure" in cookie
        assert "Path=/" in cookie

        rejected = client.post("/ui/collections", data={"name": "Animation"})
        assert rejected.status_code == 403
        assert rejected.headers["content-type"].startswith("text/html")
        assert "csrf_invalid" in rejected.text


def test_ui_lifespan_disposes_database_after_runtime_close_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = f"sqlite:///{tmp_path / 'ui-close-failure.db'}"
    migrate_to_head(database_url)
    monkeypatch.setenv("MEDIA_FINDER_UI_SECRET", "a sufficiently long test session secret")
    runtime_factory = Mock()
    runtime_factory.close.side_effect = RuntimeError("module close failed")
    app = create_ui_app(
        database_url,
        session_secret_reference="env:MEDIA_FINDER_UI_SECRET",
        runtime_factory=runtime_factory,
    )
    disposed = False
    original_dispose = app.state.engine.dispose

    def dispose() -> None:
        nonlocal disposed
        disposed = True
        original_dispose()

    monkeypatch.setattr(app.state.engine, "dispose", dispose)

    with pytest.raises(RuntimeError, match="module close failed"), TestClient(app):
        pass

    assert disposed is True


def test_ui_form_limit_rejects_declared_and_streamed_oversize_with_stable_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = f"sqlite:///{tmp_path / 'ui.db'}"
    migrate_to_head(database_url)
    monkeypatch.setenv("MEDIA_FINDER_UI_SECRET", "a sufficiently long test session secret")
    app = create_ui_app(
        database_url,
        session_secret_reference="env:MEDIA_FINDER_UI_SECRET",
    )
    with TestClient(app) as client:
        rejected = client.post(
            "/ui/collections",
            content=b"x" * (MAX_UI_FORM_BYTES + 1),
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
    assert rejected.status_code == 413
    assert 'data-error-code="ui_form_too_large"' in rejected.text
    assert "x" * 100 not in rejected.text

    chunks = iter(
        (
            {"type": "http.request", "body": b"x" * MAX_UI_FORM_BYTES, "more_body": True},
            {"type": "http.request", "body": b"yz", "more_body": False},
        )
    )

    async def receive() -> dict[str, object]:
        return next(chunks)

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [(b"content-type", b"application/x-www-form-urlencoded")],
        },
        receive,
    )
    with pytest.raises(ValueError, match="ui_form_too_large"):
        asyncio.run(decode_form(request))
