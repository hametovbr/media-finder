"""Provider-agnostic metadata catalog orchestration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime

from media_finder_sdk import (
    MetadataIdentity,
    MetadataProvider,
    MetadataRetentionPolicy,
    MetadataSearchQuery,
    MetadataSearchResult,
)

from .commands import CatalogCommands
from .models import ItemResolution
from .ports import CatalogQueryPort, CatalogUnitOfWork
from .validation import (
    catalog_identity,
    revision_draft,
    validate_normalized,
    validate_provider_payload,
    validate_retention_policy,
    validate_search_result,
)


class MetadataCatalogService:
    def __init__(
        self,
        *,
        query_port: CatalogQueryPort,
        unit_of_work: CatalogUnitOfWork,
        clock: Callable[[], datetime],
    ) -> None:
        self._queries = query_port
        self._uow = unit_of_work
        self._clock = clock

    def search(
        self,
        *,
        query: MetadataSearchQuery,
        providers: Mapping[str, MetadataProvider],
        selected_provider_ids: tuple[str, ...],
    ) -> tuple[MetadataSearchResult, ...]:
        results: list[MetadataSearchResult] = []
        for provider_id in selected_provider_ids:
            provider = providers.get(provider_id)
            if provider is None:
                raise ValueError("metadata_provider_unavailable")
            for result in provider.search(query):
                results.append(validate_search_result(result, expected_provider_id=provider_id))
        return tuple(results)

    def select(
        self,
        *,
        identity: MetadataIdentity,
        provider: MetadataProvider | Callable[[], MetadataProvider],
        retention_policy: MetadataRetentionPolicy | Callable[[], MetadataRetentionPolicy],
        confirm_similarity: bool = False,
        collection_id: str | None = None,
    ) -> ItemResolution:
        selected_identity = catalog_identity(identity)
        existing = self._queries.find_item_by_identity(selected_identity)
        if existing is not None:
            if existing.identity.media_kind != selected_identity.media_kind:
                raise ValueError("provider_identity_mismatch")
            return ItemResolution(item=existing, created=False)

        now = self._clock()
        selected_provider = provider() if callable(provider) else provider
        selected_retention = retention_policy() if callable(retention_policy) else retention_policy
        raw_payload = validate_provider_payload(selected_provider.fetch(identity))
        normalized = validate_normalized(
            selected_provider.normalize(raw_payload, identity),
            identity=identity,
        )
        if (
            self._queries.find_similar(
                normalized_title=next(iter(normalized.titles.values())).casefold(),
                year=normalized.year,
                excluding_provider_id=identity.provider_id,
            )
            and not confirm_similarity
        ):
            raise ValueError("similarity_confirmation_required")
        draft = revision_draft(
            raw_payload=raw_payload,
            normalized=normalized,
            retention=validate_retention_policy(selected_retention.retention_for(now)),
            created_at=now,
        )
        with self._uow.write() as repository:
            commands = CatalogCommands(repository=repository, clock=self._clock)
            if (
                repository.find_similar(
                    normalized_title=next(iter(normalized.titles.values())).casefold(),
                    year=normalized.year,
                    excluding_provider_id=identity.provider_id,
                )
                and not confirm_similarity
            ):
                raise ValueError("similarity_confirmation_required")
            resolution = commands.get_or_create_item(selected_identity)
            if not resolution.created:
                return resolution
            commands.append_revision(resolution.item.id, draft)
            if collection_id is not None:
                commands.move_item(resolution.item.id, collection_id)
            persisted = repository.get_item(resolution.item.id)
            if persisted is None:  # pragma: no cover - a repository contract violation
                raise RuntimeError("catalog_item_persistence_failed")
            return ItemResolution(item=persisted, created=True)


__all__ = ["MetadataCatalogService"]
