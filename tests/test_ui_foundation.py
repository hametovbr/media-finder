from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from media_finder.db import migrate_to_head
from media_finder.ui import SessionSigner, create_ui_app, error_message, resolve_locale


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


def test_signed_session_rejects_tampering() -> None:
    signer = SessionSigner(b"a sufficiently long test session secret")
    token = signer.dumps({"locale": "ru", "csrf": "fixed"})

    assert signer.loads(token) == {"locale": "ru", "csrf": "fixed"}
    with pytest.raises(ValueError, match="invalid_session"):
        signer.loads(token[:-1] + ("A" if token[-1] != "A" else "B"))


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
