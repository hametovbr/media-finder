import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from media_finder_server import create_ui_app
from sqlalchemy import func, select

from media_finder.db import migrate_to_head, session_factory
from media_finder.models import MediaItem, MetadataRevision


def _csrf(text: str) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', text)
    assert match
    return match.group(1)


@pytest.fixture
def manual_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    url = f"sqlite:///{tmp_path / 'manual-ui.db'}"
    migrate_to_head(url)
    monkeypatch.setenv("MEDIA_FINDER_UI_SECRET", "a sufficiently long test session secret")
    return create_ui_app(url, session_secret_reference="env:MEDIA_FINDER_UI_SECRET")


def test_structured_manual_series_create_and_confirmed_edit_are_immutable(manual_app) -> None:
    with TestClient(manual_app) as client:
        csrf = _csrf(client.get("/").text)
        form = client.get("/add/manual")
        assert 'data-testid="manual-structured-form"' in form.text
        assert 'name="title"' in form.text
        assert 'name="season_0_number"' in form.text
        assert 'name="season_0_episode_0_number"' in form.text

        created = client.post(
            "/ui/manual/save",
            data={
                "csrf": csrf,
                "kind": "series",
                "metadata_locale": "en",
                "title": "Structured Series",
                "year": "1999",
                "plot": "A structured series.",
                "season_0_number": "0",
                "season_0_title": "Specials",
                "season_0_episode_0_number": "1",
                "season_0_episode_0_title": "Pilot special",
            },
            follow_redirects=False,
        )
        assert created.status_code == 303
        item_id = created.headers["location"].split("/")[2].split("?")[0]

        edit = client.get(f"/items/{item_id}/edit")
        assert 'value="Structured Series"' in edit.text
        assert 'value="0"' in edit.text
        assert 'value="Pilot special"' in edit.text

        pending = client.post(
            "/ui/manual/save",
            data={
                "csrf": csrf,
                "external_id": _external_id(edit.text),
                "kind": "series",
                "metadata_locale": "en",
                "title": "Structured Series Revised",
                "year": "2000",
                "season_0_number": "0",
                "season_0_episode_0_number": "1",
                "season_0_episode_0_title": "Revised special",
            },
        )
        assert pending.status_code == 200
        assert 'data-testid="manual-revision-confirmation"' in pending.text
        confirmation = _draft_token(pending.text)

        sessions = session_factory(manual_app.state.engine)
        with sessions() as session:
            assert (
                session.scalar(
                    select(func.count(MetadataRevision.id)).where(
                        MetadataRevision.media_item_id == item_id
                    )
                )
                == 1
            )

        confirmed = client.post(
            "/ui/manual/confirm",
            data={"csrf": csrf, "draft_token": confirmation},
            follow_redirects=False,
        )
        assert confirmed.status_code == 303

    sessions = session_factory(manual_app.state.engine)
    with sessions() as session:
        item = session.get(MediaItem, item_id)
        assert item is not None
        assert (
            session.scalar(
                select(func.count(MetadataRevision.id)).where(
                    MetadataRevision.media_item_id == item_id
                )
            )
            == 2
        )
        effective = item.current_revision.effective_payload
        assert effective is not None
        assert effective["titles"]["en"] == "Structured Series Revised"
        assert effective["seasons"][0]["number"] == 0
        assert effective["seasons"][0]["episodes"][0]["title"] == "Revised special"


def test_invalid_structured_manual_input_creates_no_partial_item(manual_app) -> None:
    with TestClient(manual_app) as client:
        csrf = _csrf(client.get("/").text)
        rejected = client.post(
            "/ui/manual/save",
            data={
                "csrf": csrf,
                "kind": "series",
                "metadata_locale": "en",
                "title": "Broken hierarchy",
                "season_0_number": "0",
                "season_0_episode_0_number": "not-a-number",
                "season_0_episode_0_title": "Broken",
            },
        )
        assert rejected.status_code == 422
        assert "manual_import_invalid" in rejected.text

    sessions = session_factory(manual_app.state.engine)
    with sessions() as session:
        assert session.scalar(select(func.count(MediaItem.id))) == 0


def test_structured_parser_accepts_multiple_seasons_episodes_and_removed_index_gaps(
    manual_app,
) -> None:
    with TestClient(manual_app) as client:
        csrf = _csrf(client.get("/").text)
        editor = client.get("/add/manual")
        assert 'data-action="add-season"' in editor.text
        assert 'data-action="add-episode"' in editor.text
        assert 'data-action="remove-season"' in editor.text
        assert 'data-action="remove-episode"' in editor.text

        created = client.post(
            "/ui/manual/save",
            data={
                "csrf": csrf,
                "kind": "series",
                "metadata_locale": "en",
                "title": "Arbitrary hierarchy",
                "season_2_number": "0",
                "season_2_title": "Specials",
                "season_2_episode_3_number": "1",
                "season_2_episode_3_title": "Special one",
                "season_9_number": "2",
                "season_9_title": "Second season",
                "season_9_episode_4_number": "1",
                "season_9_episode_4_title": "Episode one",
                "season_9_episode_8_number": "2",
                "season_9_episode_8_title": "Episode two",
            },
            follow_redirects=False,
        )
        assert created.status_code == 303
        item_id = created.headers["location"].split("/")[2].split("?")[0]

    sessions = session_factory(manual_app.state.engine)
    with sessions() as session:
        item = session.get(MediaItem, item_id)
        assert item is not None and item.current_revision is not None
        effective = item.current_revision.effective_payload
        assert effective is not None
        assert [season["number"] for season in effective["seasons"]] == [0, 2]
        assert [episode["title"] for episode in effective["seasons"][1]["episodes"]] == [
            "Episode one",
            "Episode two",
        ]


def test_existing_json_import_requires_explicit_bounded_confirmation(manual_app) -> None:
    document = {
        "schema_version": "1",
        "kind": "movie",
        "locale": "en",
        "titles": {"en": "JSON title"},
    }
    with TestClient(manual_app) as client:
        csrf = _csrf(client.get("/").text)
        created = client.post(
            "/ui/manual/import",
            data={"csrf": csrf, "document": json.dumps(document)},
            follow_redirects=False,
        )
        assert created.status_code == 303
        item_id = created.headers["location"].split("/")[2].split("?")[0]
        external_id = _external_id(client.get(f"/items/{item_id}/edit").text)
        document["external_id"] = external_id.upper()
        document["titles"] = {"en": "JSON revised"}

        pending = client.post(
            "/ui/manual/import", data={"csrf": csrf, "document": json.dumps(document)}
        )
        assert pending.status_code == 200
        assert 'data-testid="manual-revision-confirmation"' in pending.text
        token = _draft_token(pending.text)

        sessions = session_factory(manual_app.state.engine)
        with sessions() as session:
            assert session.scalar(select(func.count(MetadataRevision.id))) == 1

        confirmed = client.post(
            "/ui/manual/confirm",
            data={"csrf": csrf, "draft_token": token},
            follow_redirects=False,
        )
        assert confirmed.status_code == 303
        expired = client.post("/ui/manual/confirm", data={"csrf": csrf, "draft_token": token})
        assert expired.status_code == 410
        assert 'data-error-code="manual_draft_expired"' in expired.text

    sessions = session_factory(manual_app.state.engine)
    with sessions() as session:
        assert session.scalar(select(func.count(MetadataRevision.id))) == 2
        item = session.scalar(select(MediaItem))
        assert item is not None
        assert item.external_id == external_id
        assert item.current_revision is not None
        assert item.current_revision.effective_payload["titles"]["en"] == "JSON revised"


def test_manual_confirmation_uses_resolved_request_locale(manual_app) -> None:
    document = {
        "schema_version": "1",
        "external_id": "f71a7700-8e46-4f7d-8df0-5a394803cc43",
        "kind": "movie",
        "locale": "ru",
        "titles": {"ru": "Локализованный тайтл"},
    }
    with TestClient(manual_app) as client:
        csrf = _csrf(client.get("/", headers={"Accept-Language": "ru"}).text)
        assert (
            client.post(
                "/ui/manual/import",
                data={"csrf": csrf, "document": json.dumps(document)},
                follow_redirects=False,
            ).status_code
            == 303
        )
        pending = client.post(
            "/ui/manual/import",
            data={"csrf": csrf, "document": json.dumps(document)},
            headers={"Accept-Language": "ru"},
        )

    assert pending.status_code == 200
    assert "Подтвердить ревизию метаданных" in pending.text
    assert "Confirm metadata revision" not in pending.text


def _external_id(text: str) -> str:
    match = re.search(r'name="external_id" value="([^"]+)"', text)
    assert match
    return match.group(1)


def _draft_token(text: str) -> str:
    match = re.search(r'name="draft_token" value="([^"]+)"', text)
    assert match
    return match.group(1)
