# ruff: noqa: RUF001
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from media_finder.db import migrate_to_head, session_factory
from media_finder.models import Acquisition, DownloadClientInstance, MediaItem
from media_finder.ui import create_ui_app


def _csrf(text: str) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', text)
    assert match
    return match.group(1)


@pytest.fixture
def feedback_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database_url = f"sqlite:///{tmp_path / 'feedback.db'}"
    migrate_to_head(database_url)
    monkeypatch.setenv("MEDIA_FINDER_UI_SECRET", "a sufficiently long test session secret")
    return create_ui_app(database_url, session_secret_reference="env:MEDIA_FINDER_UI_SECRET")


def test_same_stable_error_code_has_localized_message_and_csrf_is_localized(
    feedback_app,
) -> None:
    with TestClient(feedback_app) as client:
        en_csrf = _csrf(client.get("/", headers={"Accept-Language": "en"}).text)
        english = client.post("/ui/manual/import", data={"csrf": en_csrf, "document": "{"})
        assert english.status_code == 422
        assert 'data-error-code="manual_import_invalid"' in english.text
        assert "Manual metadata is invalid." in english.text

        switched = client.post(
            "/ui/locale",
            data={"csrf": en_csrf, "locale": "ru"},
            follow_redirects=False,
        )
        assert switched.status_code == 303
        russian = client.post("/ui/manual/import", data={"csrf": en_csrf, "document": "{"})
        assert russian.status_code == 422
        assert 'data-error-code="manual_import_invalid"' in russian.text
        assert "Ручные метаданные неверны." in russian.text
        assert "Manual metadata is invalid." not in russian.text

        rejected = client.post("/ui/collections", data={"csrf": "wrong", "name": "x"})
        assert rejected.status_code == 403
        assert 'data-error-code="csrf_invalid"' in rejected.text
        assert "Запрос отклонён." in rejected.text
        assert "Request rejected." not in rejected.text


def test_failed_acquisition_fragment_localizes_status_and_failure_code(feedback_app) -> None:
    document = {
        "schema_version": "1",
        "kind": "movie",
        "locale": "en",
        "titles": {"en": "Failure"},
    }
    with TestClient(feedback_app) as client:
        csrf = _csrf(client.get("/").text)
        created = client.post(
            "/ui/manual/import",
            data={"csrf": csrf, "document": json.dumps(document)},
            follow_redirects=False,
        )
        item_id = created.headers["location"].split("/")[2].split("?")[0]

    sessions = session_factory(feedback_app.state.engine)
    with sessions() as database:
        item = database.scalar(select(MediaItem).where(MediaItem.id == item_id))
        assert item is not None and item.current_revision_id is not None
        instance = DownloadClientInstance(name="failure", module_key="fixture", config_payload={})
        database.add(instance)
        database.flush()
        database.add(
            Acquisition(
                media_item_id=item.id,
                metadata_revision_id=item.current_revision_id,
                download_client_instance_id=instance.id,
                idempotency_key="failed-feedback",
                naming_profile="jellyfin-v1",
                status="failed",
                failure_code="download_client_rejected",
            )
        )
        database.commit()

    with TestClient(feedback_app) as client:
        root = client.get("/", headers={"Accept-Language": "ru"})
        csrf = _csrf(root.text)
        fragment = client.get(
            f"/ui/items/{item_id}/tabs/acquisitions",
            headers={"Accept-Language": "ru"},
        )

    assert fragment.status_code == 200
    assert "Не удалось отправить" in fragment.text
    assert "Клиент загрузки отклонил загрузку." in fragment.text
    assert "download_client_rejected" not in fragment.text
    assert 'name="csrf" value=' in root.text
