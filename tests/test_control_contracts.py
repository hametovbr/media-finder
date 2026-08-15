import inspect

import pytest
from media_finder_control import (
    AcquisitionStatus,
    BrowserSecurityPort,
    BrowserSession,
    ControlError,
    ControlFailure,
    ControlGateway,
    Locale,
    ManualDocumentV1,
    MediaKind,
    Page,
    PageRequest,
)
from media_finder_control.manual import EpisodeDocument, SeasonDocument
from pydantic import ValidationError

from media_finder.modules.manual import (
    EpisodeDocument as ProviderEpisodeDocument,
)
from media_finder.modules.manual import (
    ManualDocumentV1 as ProviderManualDocumentV1,
)
from media_finder.modules.manual import (
    SeasonDocument as ProviderSeasonDocument,
)


def test_public_models_are_immutable_and_errors_are_language_neutral() -> None:
    error = ControlError(code="collection_not_found", request_id="req-1", details={"id": "c1"})

    with pytest.raises(ValidationError):
        error.code = "localized prose"  # type: ignore[misc]

    failure = ControlFailure(code="selection_expired", status=410, details={"kind": "metadata"})
    assert failure.error == ControlError(
        code="selection_expired", request_id=None, details={"kind": "metadata"}
    )
    assert str(failure) == "selection_expired"


def test_public_enums_and_bounded_page_contract() -> None:
    assert set(Locale) == {Locale.EN, Locale.RU}
    assert set(MediaKind) == {MediaKind.MOVIE, MediaKind.SERIES}
    assert set(AcquisitionStatus) == {
        AcquisitionStatus.PENDING,
        AcquisitionStatus.SUBMITTED,
        AcquisitionStatus.FAILED,
    }
    assert PageRequest().limit == 50
    assert Page[int](items=(1, 2), next_cursor=None).items == (1, 2)

    with pytest.raises(ValidationError):
        PageRequest(limit=101)


def test_manual_browser_document_has_provider_schema_v1_parity() -> None:
    contract = ManualDocumentV1.model_json_schema()
    provider = ProviderManualDocumentV1.model_json_schema()

    assert set(contract["properties"]) == set(provider["properties"])
    assert set(SeasonDocument.model_json_schema()["properties"]) == set(
        ProviderSeasonDocument.model_json_schema()["properties"]
    )
    assert set(EpisodeDocument.model_json_schema()["properties"]) == set(
        ProviderEpisodeDocument.model_json_schema()["properties"]
    )
    document = ManualDocumentV1.model_validate(
        {
            "schema_version": "1",
            "external_id": "E0A465BB-34EB-4565-BDE2-B80D6E789B7C",
            "kind": "series",
            "locale": "ru",
            "titles": {"ru": "Example", "en": "Example"},
            "ratings": [{"source": "local", "value": 8.5, "votes": 2}],
            "people": [{"name": "Person", "role": "director"}],
            "artwork": [{"kind": "poster", "url": "https://example.test/poster.jpg"}],
            "seasons": [
                {
                    "number": 0,
                    "provider_ids": {"manual": "s0"},
                    "episodes": [
                        {
                            "number": 1,
                            "title": "Special",
                            "runtime_minutes": 12,
                            "provider_ids": {"manual": "e1"},
                            "ordering": 1,
                        }
                    ],
                }
            ],
        }
    )
    assert document.external_id == "e0a465bb-34eb-4565-bde2-b80d6e789b7c"
    assert document.seasons[0].episodes[0].title == "Special"


def test_control_ports_are_async_and_framework_independent() -> None:
    gateway_methods = {
        name
        for name, member in inspect.getmembers(ControlGateway)
        if inspect.iscoroutinefunction(member) and not name.startswith("_")
    }
    security_methods = {
        name
        for name, member in inspect.getmembers(BrowserSecurityPort)
        if inspect.iscoroutinefunction(member) and not name.startswith("_")
    }

    assert {
        "list_collections",
        "list_media_items",
        "get_media_item",
        "search_metadata",
        "select_metadata",
        "import_manual",
        "edit_manual",
        "import_episodes",
        "search_releases",
        "list_destinations",
        "submit_acquisition",
        "reconcile_acquisition",
        "integration_diagnostics",
        "about",
    } <= gateway_methods
    assert security_methods == {"load_session", "serialize_session", "validate_csrf"}
    assert BrowserSession(ui_locale=Locale.EN, metadata_locale=Locale.RU, csrf_token="x")
