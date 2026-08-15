import json
import re

from fastapi.testclient import TestClient
from media_finder_builtin_ui import create_builtin_ui
from media_finder_builtin_ui.fake import FakeBrowserSecurity, FakeControlGateway


def _csrf(html: str) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


def test_metadata_and_manual_html_workflows_run_against_fake_ports() -> None:
    with TestClient(
        create_builtin_ui(
            gateway=FakeControlGateway(),
            security=FakeBrowserSecurity(),
        )
    ) as client:
        add = client.get("/add")
        csrf = _csrf(add.text)
        search = client.post(
            "/ui/metadata/search",
            data={"csrf": csrf, "query": "Example"},
        )
        assert search.status_code == 200
        assert 'data-testid="provider-results-tmdb"' in search.text
        assert "metadata-1" in search.text

        selected = client.post(
            "/ui/metadata/confirm",
            data={"csrf": csrf, "selection_token": "metadata-1"},
            follow_redirects=False,
        )
        assert selected.status_code == 303
        assert selected.headers["location"].startswith("/items/series-1")

        editor = client.get("/add/manual")
        assert editor.status_code == 200
        assert 'data-testid="manual-structured-form"' in editor.text
        saved = client.post(
            "/ui/manual/save",
            data={
                "csrf": csrf,
                "kind": "movie",
                "metadata_locale": "en",
                "title": "Local Movie",
            },
            follow_redirects=False,
        )
        assert saved.status_code == 303

        existing_document = {
            "schema_version": "1",
            "external_id": "e0a465bb-34eb-4565-bde2-b80d6e789b7c",
            "kind": "movie",
            "locale": "en",
            "titles": {"en": "Updated"},
        }
        warning = client.post(
            "/ui/manual/import",
            data={"csrf": csrf, "document": json.dumps(existing_document)},
        )
        assert warning.status_code == 200
        assert 'data-testid="manual-revision-confirmation"' in warning.text
        token = re.search(r'name="draft_token" value="([^"]+)"', warning.text)
        assert token is not None
        confirmed = client.post(
            "/ui/manual/confirm",
            data={"csrf": csrf, "draft_token": token.group(1)},
            follow_redirects=False,
        )
        assert confirmed.status_code == 303

        csv = client.post(
            "/ui/items/series-1/manual/csv",
            data={"csrf": csrf, "content": "season,episode,title\n1,1,Pilot\n"},
            follow_redirects=False,
        )
        assert csv.status_code == 303


def test_manual_editor_round_trips_existing_rich_contract_data() -> None:
    with TestClient(
        create_builtin_ui(
            gateway=FakeControlGateway(),
            security=FakeBrowserSecurity(),
        )
    ) as client:
        page = client.get("/items/movie-1/edit")
    assert page.status_code == 200
    assert 'value="e0a465bb-34eb-4565-bde2-b80d6e789b7c"' in page.text
    assert 'value="Example Movie"' in page.text
