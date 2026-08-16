"""Shared browser-control scenario drivers for real-facade conformance tests."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

from fastapi.testclient import TestClient
from media_finder_control import ControlFailure, Locale
from media_finder_control.manual import ManualDocumentV1
from media_finder_control.models import (
    AcquisitionSubmissionRequest,
    EpisodeImportRequest,
    ManualImportRequest,
    MetadataSearchRequest,
    MetadataSelectionRequest,
    ReleaseSearchRequest,
)
from media_finder_control.ports import ControlGateway
from pydantic import JsonValue


@dataclass(frozen=True, slots=True)
class DriverFailure(Exception):
    code: str
    status: int
    details: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class SelectedItem:
    item: dict[str, JsonValue]
    created: bool


class ControlDriver(Protocol):
    def get_item(self, item_id: str) -> dict[str, JsonValue]: ...

    def search_metadata(self, query: str) -> tuple[dict[str, JsonValue], ...]: ...

    def select_metadata(self, token: str, *, confirm: bool = False) -> SelectedItem: ...

    def import_manual(self, document: dict[str, JsonValue]) -> SelectedItem: ...

    def confirm_manual(self, token: str) -> SelectedItem: ...

    def edit_manual(self, item_id: str, document: dict[str, JsonValue]) -> SelectedItem: ...

    def import_episodes(self, item_id: str, csv: str) -> dict[str, JsonValue]: ...

    def search_releases(self, item_id: str, query: str) -> tuple[dict[str, JsonValue], ...]: ...

    def destinations(self) -> tuple[dict[str, JsonValue], ...]: ...

    def submit(
        self,
        *,
        item_id: str,
        release_token: str,
        destination: str,
        idempotency_key: str,
    ) -> dict[str, JsonValue]: ...

    def reconcile(self, acquisition_id: str) -> dict[str, JsonValue]: ...


def _json(value: object) -> dict[str, JsonValue]:
    return value.model_dump(mode="json")  # type: ignore[no-any-return,union-attr]


def _json_tuple(values: object) -> tuple[dict[str, JsonValue], ...]:
    return tuple(_json(value) for value in values)  # type: ignore[union-attr]


def _run[T](operation) -> T:  # type: ignore[no-untyped-def]
    try:
        return asyncio.run(operation)
    except ControlFailure as error:
        raise DriverFailure(
            code=error.error.code,
            status=error.status,
            details=error.error.details,
        ) from None


class DirectControlDriver:
    def __init__(self, gateway: ControlGateway) -> None:
        self._gateway = gateway

    def get_item(self, item_id: str) -> dict[str, JsonValue]:
        return _json(_run(self._gateway.get_media_item(item_id=item_id, locale=Locale.EN)))

    def search_metadata(self, query: str) -> tuple[dict[str, JsonValue], ...]:
        return _json_tuple(
            _run(
                self._gateway.search_metadata(
                    request=MetadataSearchRequest(query=query, locale=Locale.EN)
                )
            )
        )

    def select_metadata(self, token: str, *, confirm: bool = False) -> SelectedItem:
        result = _run(
            self._gateway.select_metadata(
                token=token,
                request=MetadataSelectionRequest(confirm_similarity=confirm),
                locale=Locale.EN,
            )
        )
        return SelectedItem(item=_json(result.item), created=result.created)

    def import_manual(self, document: dict[str, JsonValue]) -> SelectedItem:
        result = _run(
            self._gateway.import_manual(
                request=ManualImportRequest(document=ManualDocumentV1.model_validate(document))
            )
        )
        return self._manual_result(result)

    def confirm_manual(self, token: str) -> SelectedItem:
        return self._manual_result(_run(self._gateway.confirm_manual(token=token)))

    def edit_manual(self, item_id: str, document: dict[str, JsonValue]) -> SelectedItem:
        result = _run(
            self._gateway.edit_manual(
                item_id=item_id,
                document=ManualDocumentV1.model_validate(document),
            )
        )
        return self._manual_result(result)

    def import_episodes(self, item_id: str, csv: str) -> dict[str, JsonValue]:
        return _json(
            _run(
                self._gateway.import_episodes(
                    item_id=item_id,
                    request=EpisodeImportRequest(csv=csv),
                    locale=Locale.EN,
                )
            )
        )

    def search_releases(self, item_id: str, query: str) -> tuple[dict[str, JsonValue], ...]:
        return _json_tuple(
            _run(
                self._gateway.search_releases(
                    item_id=item_id,
                    request=ReleaseSearchRequest(query=query),
                )
            )
        )

    def destinations(self) -> tuple[dict[str, JsonValue], ...]:
        return _json_tuple(_run(self._gateway.list_destinations()))

    def submit(
        self,
        *,
        item_id: str,
        release_token: str,
        destination: str,
        idempotency_key: str,
    ) -> dict[str, JsonValue]:
        return _json(
            _run(
                self._gateway.submit_acquisition(
                    request=AcquisitionSubmissionRequest(
                        media_item_id=item_id,
                        release_token=release_token,
                        destination=destination,
                        idempotency_key=idempotency_key,
                    )
                )
            )
        )

    def reconcile(self, acquisition_id: str) -> dict[str, JsonValue]:
        return _json(_run(self._gateway.reconcile_acquisition(acquisition_id=acquisition_id)))

    @staticmethod
    def _manual_result(result) -> SelectedItem:  # type: ignore[no-untyped-def]
        if result.confirmation_token is not None:
            raise DriverFailure(
                code="confirmation_required",
                status=409,
                details={
                    "confirmation_token": result.confirmation_token,
                    "kind": "manual",
                },
            )
        if result.item is None:
            raise DriverFailure(code="manual_import_invalid", status=422, details={})
        return SelectedItem(item=_json(result.item), created=result.created)


class HttpControlDriver:
    def __init__(self, client: TestClient) -> None:
        self._client = client
        session = self._client.get("/v1/session")
        if session.status_code != 200:
            raise AssertionError("control_session_bootstrap_failed")
        self._headers = {
            "Origin": "http://testserver",
            "X-CSRF-Token": session.json()["csrf_token"],
        }

    def get_item(self, item_id: str) -> dict[str, JsonValue]:
        return self._response(self._client.get(f"/v1/media-items/{item_id}"))[0]

    def search_metadata(self, query: str) -> tuple[dict[str, JsonValue], ...]:
        response = self._response(
            self._client.post(
                "/v1/metadata-searches",
                json={"query": query, "locale": "en"},
                headers=self._headers,
            )
        )[0]
        return tuple(response)  # type: ignore[arg-type,return-value]

    def select_metadata(self, token: str, *, confirm: bool = False) -> SelectedItem:
        body, status = self._response(
            self._client.post(
                f"/v1/metadata-selections/{token}",
                json={"confirm_similarity": confirm},
                headers=self._headers,
            )
        )
        return SelectedItem(item=body, created=status == 201)

    def import_manual(self, document: dict[str, JsonValue]) -> SelectedItem:
        body, status = self._response(
            self._client.post(
                "/v1/manual-imports",
                json={"document": document},
                headers=self._headers,
            )
        )
        return SelectedItem(item=body, created=status == 201)

    def confirm_manual(self, token: str) -> SelectedItem:
        body, status = self._response(
            self._client.post(
                f"/v1/manual-imports/{token}/confirm",
                json={},
                headers=self._headers,
            )
        )
        return SelectedItem(item=body, created=status == 201)

    def edit_manual(self, item_id: str, document: dict[str, JsonValue]) -> SelectedItem:
        body, status = self._response(
            self._client.put(
                f"/v1/media-items/{item_id}/manual-metadata",
                json=document,
                headers=self._headers,
            )
        )
        return SelectedItem(item=body, created=status == 201)

    def import_episodes(self, item_id: str, csv: str) -> dict[str, JsonValue]:
        return self._response(
            self._client.post(
                f"/v1/media-items/{item_id}/episode-imports",
                json={"csv": csv},
                headers=self._headers,
            )
        )[0]

    def search_releases(self, item_id: str, query: str) -> tuple[dict[str, JsonValue], ...]:
        body = self._response(
            self._client.post(
                f"/v1/media-items/{item_id}/release-searches",
                json={"query": query},
                headers=self._headers,
            )
        )[0]
        return tuple(body)  # type: ignore[arg-type,return-value]

    def destinations(self) -> tuple[dict[str, JsonValue], ...]:
        body = self._response(self._client.get("/v1/download-destinations"))[0]
        return tuple(body)  # type: ignore[arg-type,return-value]

    def submit(
        self,
        *,
        item_id: str,
        release_token: str,
        destination: str,
        idempotency_key: str,
    ) -> dict[str, JsonValue]:
        return self._response(
            self._client.post(
                "/v1/acquisitions",
                json={
                    "media_item_id": item_id,
                    "release_token": release_token,
                    "destination": destination,
                    "idempotency_key": idempotency_key,
                },
                headers=self._headers,
            )
        )[0]

    def reconcile(self, acquisition_id: str) -> dict[str, JsonValue]:
        return self._response(
            self._client.post(
                f"/v1/acquisitions/{acquisition_id}/reconcile",
                json={},
                headers=self._headers,
            )
        )[0]

    @staticmethod
    def _response(response) -> tuple[dict[str, JsonValue], int]:  # type: ignore[no-untyped-def]
        body = response.json()
        if response.status_code >= 400:
            error = body["error"]
            raise DriverFailure(
                code=error["code"],
                status=response.status_code,
                details=error.get("details", {}),
            )
        return body, response.status_code


__all__ = [
    "ControlDriver",
    "DirectControlDriver",
    "DriverFailure",
    "HttpControlDriver",
    "SelectedItem",
]
