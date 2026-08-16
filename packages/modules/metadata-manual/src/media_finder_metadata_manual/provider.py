"""Manual metadata retrieval capability."""

from __future__ import annotations

from collections.abc import Mapping

from media_finder_sdk import (
    MediaKind,
    MetadataIdentity,
    MetadataSearchQuery,
    MetadataSearchResult,
    ModuleError,
    ModuleFailureCategory,
    NormalizedMetadata,
    ProviderPayload,
)
from pydantic import ValidationError

from .document import ManualDocumentV1

type ManualFixtureKey = tuple[MediaKind, str, str]
type ManualFixtures = Mapping[ManualFixtureKey, ProviderPayload]


def invalid_manual_input() -> ModuleError:
    return ModuleError(
        category=ModuleFailureCategory.INVALID_IDENTITY,
        code="manual_import_invalid",
    )


class ManualProvider:
    def __init__(self, fixtures: ManualFixtures | None = None) -> None:
        self._fixtures = dict(fixtures or {})
        self._closed = False

    def validate(self) -> None:
        if self._closed:
            raise ModuleError(
                category=ModuleFailureCategory.UNAVAILABLE,
                code="manual_provider_closed",
            )

    def search(self, query: MetadataSearchQuery) -> tuple[MetadataSearchResult, ...]:
        needle = query.query.casefold().strip()
        results: list[MetadataSearchResult] = []
        try:
            for (kind, external_id, locale), payload in self._fixtures.items():
                if locale != query.locale or kind not in query.media_kinds:
                    continue
                document = ManualDocumentV1.model_validate(payload.data)
                title = document.titles.get(locale) or next(iter(document.titles.values()))
                if needle not in title.casefold():
                    continue
                results.append(
                    MetadataSearchResult(
                        provider_id="manual",
                        external_id=external_id,
                        media_kind=kind,
                        title=title,
                        year=document.year,
                        locale=locale,
                    )
                )
        except (ValidationError, ValueError, TypeError, StopIteration):
            raise invalid_manual_input() from None
        return tuple(results[: query.limit])

    def fetch(self, identity: MetadataIdentity) -> ProviderPayload:
        payload = self._fixtures.get((identity.media_kind, identity.external_id, identity.locale))
        if identity.provider_id != "manual" or payload is None:
            raise invalid_manual_input()
        return payload

    def normalize(self, payload: ProviderPayload, identity: MetadataIdentity) -> NormalizedMetadata:
        try:
            document = ManualDocumentV1.model_validate(payload.data)
            return document.normalized(identity)
        except (ValidationError, ValueError, TypeError):
            raise invalid_manual_input() from None

    def close(self) -> None:
        self._closed = True


__all__: list[str] = []
