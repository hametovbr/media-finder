import asyncio

from fastapi.testclient import TestClient
from media_finder_builtin_ui.dev import create_dev_app
from media_finder_builtin_ui.fake import FakeControlGateway
from media_finder_builtin_ui.i18n import message_for
from media_finder_control import AcquisitionStatus, Locale, PageRequest
from media_finder_control.manual import ManualDocumentV1
from media_finder_control.models import (
    AcquisitionSubmissionRequest,
    ManualImportRequest,
    MetadataSearchRequest,
)


def test_fake_gateway_covers_critical_deterministic_states() -> None:
    async def scenario() -> None:
        gateway = FakeControlGateway()
        english = await gateway.list_media_items(
            locale=Locale.EN,
            page=PageRequest(),
            collection_id=None,
            uncategorized=False,
            archived=False,
        )
        russian = await gateway.list_media_items(
            locale=Locale.RU,
            page=PageRequest(),
            collection_id=None,
            uncategorized=False,
            archived=False,
        )
        assert [item.title for item in english.items] == ["Example Movie", "Example Series"]
        assert [item.title for item in russian.items] == ["Пример фильма", "Пример сериала"]

        series = await gateway.get_media_item(item_id="series-1", locale=Locale.EN)
        assert series.metadata.seasons[0].number == 0
        assert series.metadata.seasons[0].episodes[0].title == "Special"

        results = await gateway.search_metadata(
            request=MetadataSearchRequest(query="duplicate", locale=Locale.EN)
        )
        assert results[0].token == "metadata-duplicate"
        duplicate = await gateway.import_manual(
            request=ManualImportRequest(
                document=ManualDocumentV1(
                    external_id="e0a465bb-34eb-4565-bde2-b80d6e789b7c",
                    kind="movie",
                    locale="en",
                    titles={"en": "Existing Manual"},
                )
            )
        )
        assert duplicate.item is None
        assert duplicate.confirmation_token == "manual-confirmation"

        diagnostics = await gateway.integration_diagnostics()
        assert {entry.status for entry in diagnostics} >= {"ready", "unavailable"}
        pending = await gateway.submit_acquisition(
            request=AcquisitionSubmissionRequest(
                media_item_id="movie-1",
                release_token="release-pending",
                destination="movies",
                idempotency_key="fake-acquisition",
            )
        )
        assert pending.status is AcquisitionStatus.PENDING
        assert (await gateway.reconcile_acquisition(acquisition_id=pending.id)).status is (
            AcquisitionStatus.SUBMITTED
        )

    asyncio.run(scenario())


def test_dev_host_renders_english_and_russian_without_backend_services() -> None:
    with TestClient(create_dev_app()) as client:
        english = client.get("/", headers={"Accept-Language": "en"})
    with TestClient(create_dev_app()) as client:
        russian = client.get("/", headers={"Accept-Language": "ru"})

    assert english.status_code == 200
    assert "Example Movie" in english.text
    assert "Example Series" in english.text
    assert russian.status_code == 200
    assert "Пример фильма" in russian.text
    assert "Пример сериала" in russian.text
    assert message_for("csrf_invalid", "en") == "Request rejected."
    assert message_for("csrf_invalid", "ru") == "Запрос отклонён."
