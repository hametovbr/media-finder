import inspect
import json

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
from media_finder_metadata_manual import registration
from media_finder_sdk import MetadataImportDocument, resolve_module_environment
from pydantic import ValidationError


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


def test_manual_browser_document_is_accepted_by_the_public_module_editor() -> None:
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
    module = registration()
    assert module.editor is not None
    editor = module.editor(resolve_module_environment(module.manifest, {}))
    result = editor.import_document(
        MetadataImportDocument.from_bytes(
            json.dumps(document.model_dump(mode="json")).encode("utf-8")
        )
    )
    assert result.identity.external_id == document.external_id
    assert result.metadata.seasons[0].episodes[0].title == "Special"


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
