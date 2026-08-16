import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from media_finder_core.platform.database import migrate_to_head
from media_finder_server import create_ui_app


def _csrf(text: str) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', text)
    assert match
    return match.group(1)


def test_redirect_result_queries_render_announced_focusable_feedback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = f"sqlite:///{tmp_path / 'semantic.db'}"
    migrate_to_head(database_url)
    monkeypatch.setenv("MEDIA_FINDER_UI_SECRET", "a sufficiently long test session secret")
    app = create_ui_app(database_url, session_secret_reference="env:MEDIA_FINDER_UI_SECRET")
    with TestClient(app) as client:
        root = client.get("/")
        assert '<script src="/static/ui.js" defer></script>' in root.text
        csrf = _csrf(root.text)
        created = client.post(
            "/ui/manual/import",
            data={
                "csrf": csrf,
                "document": json.dumps(
                    {
                        "schema_version": "1",
                        "kind": "movie",
                        "locale": "en",
                        "titles": {"en": "Feedback"},
                    }
                ),
            },
            follow_redirects=False,
        )
        item_id = created.headers["location"].split("/")[2].split("?")[0]

        for query, expected in (
            ("saved=1", "Title saved."),
            ("duplicate=1", "This title already exists."),
            ("acquisition=pending", "Pending submission"),
            ("reconciled=failed", "Submission failed"),
        ):
            page = client.get(f"/items/{item_id}?{query}")
            assert 'role="status"' in page.text
            assert 'aria-live="polite"' in page.text
            assert "data-autofocus" in page.text
            assert expected in page.text
            assert "progress" not in page.text.casefold()

        settings = client.get("/settings?saved=1")
        assert "Settings saved." not in settings.text
        assert 'form action="/ui/settings/' not in settings.text
