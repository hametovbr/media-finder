"""Core transaction orchestration for the data-only Manual metadata module."""

from typing import Any, Protocol
from uuid import UUID, uuid4

from .domain import CatalogService, RevisionInput
from .models import MediaItem
from .modules.manual import ManualImportError
from .sdk.types import MediaKind, NormalizedMetadata


class ManualMetadataModule(Protocol):
    def validate_import_identity(
        self, payload: dict[str, Any]
    ) -> tuple[str | None, MediaKind, str]: ...

    def normalize(
        self, payload: dict[str, Any], kind: str, external_id: str, locale: str
    ) -> NormalizedMetadata: ...

    def merge_episode_csv(
        self, current: NormalizedMetadata, content: str
    ) -> NormalizedMetadata: ...


class ManualCatalogService:
    def __init__(self, catalog: CatalogService, provider: ManualMetadataModule) -> None:
        self.catalog = catalog
        self.provider = provider

    def import_json(self, payload: dict[str, Any], *, confirm_existing: bool = False) -> MediaItem:
        try:
            supplied, kind, locale = self.provider.validate_import_identity(payload)
            identity = self._identity(supplied)
            normalized = self.provider.normalize(payload, kind.value, identity, locale)
            item, created = self.catalog.get_or_create_item("manual", identity, kind)
            if created or confirm_existing:
                self.catalog.add_revision(
                    item, RevisionInput(normalized=normalized, raw_payload=payload)
                )
            return item
        except Exception:
            self.catalog.session.rollback()
            raise

    def import_episode_csv(self, media_item_id: str, content: str) -> MediaItem:
        item = self.catalog.session.get(MediaItem, media_item_id)
        if item is None or item.provider_key != "manual" or item.kind != "series":
            raise ManualImportError("episode CSV target must be a Manual series")
        current = item.current_revision
        if current is None or current.effective_payload is None:
            raise ManualImportError("Manual series has no current metadata")
        try:
            normalized = NormalizedMetadata.model_validate(current.effective_payload)
            updated = self.provider.merge_episode_csv(normalized, content)
            self.catalog.add_revision(
                item,
                RevisionInput(normalized=updated, raw_payload={"episode_csv": content}),
            )
            return item
        except Exception:
            self.catalog.session.rollback()
            raise

    @staticmethod
    def _identity(supplied: str | None) -> str:
        if supplied is None:
            return str(uuid4())
        parsed = UUID(supplied)
        if parsed.version != 4:
            raise ManualImportError("Manual external_id must be a UUIDv4")
        return str(parsed)
