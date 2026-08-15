"""Core transaction orchestration for metadata-editor operations."""

import json
from typing import Any

from media_finder_sdk import (
    EpisodeTableDocument,
    MetadataEditor,
    MetadataImportDocument,
)
from media_finder_sdk import (
    NormalizedMetadata as SDKNormalizedMetadata,
)

from .domain import CatalogService, RevisionInput
from .models import MediaItem
from .sdk.types import MediaKind, NormalizedMetadata


def _legacy_metadata(metadata: SDKNormalizedMetadata) -> NormalizedMetadata:
    payload = metadata.model_dump(mode="json")
    provenance = payload["provenance"]
    if not isinstance(provenance, dict):
        raise ValueError("manual_provenance_invalid")
    provenance["provider_key"] = provenance.pop("provider_id")
    return NormalizedMetadata.model_validate(payload)


def _sdk_metadata(metadata: NormalizedMetadata) -> SDKNormalizedMetadata:
    payload = metadata.model_dump(mode="json")
    provenance = payload["provenance"]
    if not isinstance(provenance, dict):
        raise ValueError("manual_provenance_invalid")
    provenance["provider_id"] = provenance.pop("provider_key")
    return SDKNormalizedMetadata.model_validate(payload)


class ManualCatalogService:
    def __init__(
        self,
        catalog: CatalogService,
        editor: MetadataEditor,
        provider_id: str,
    ) -> None:
        self.catalog = catalog
        self.editor = editor
        self.provider_id = provider_id

    def import_json(self, payload: dict[str, Any], *, confirm_existing: bool = False) -> MediaItem:
        try:
            result = self.editor.import_document(
                MetadataImportDocument.from_bytes(json.dumps(payload).encode("utf-8"))
            )
            identity = result.identity
            normalized = _legacy_metadata(result.metadata)
            item, created = self.catalog.get_or_create_item(
                identity.provider_id,
                identity.external_id,
                MediaKind(identity.media_kind.value),
            )
            if created or confirm_existing:
                raw_payload = result.raw_payload.model_dump(mode="json")["data"]
                if not isinstance(raw_payload, dict):
                    raise ValueError("manual_raw_payload_invalid")
                self.catalog.add_revision(
                    item,
                    RevisionInput(normalized=normalized, raw_payload=raw_payload),
                )
            return item
        except Exception:
            self.catalog.session.rollback()
            raise

    def import_episode_csv(self, media_item_id: str, content: str) -> MediaItem:
        item = self.catalog.session.get(MediaItem, media_item_id)
        if item is None or item.provider_key != self.provider_id or item.kind != "series":
            raise ValueError("manual_episode_target_invalid")
        current = item.current_revision
        if current is None or current.effective_payload is None:
            raise ValueError("manual_metadata_missing")
        try:
            normalized = NormalizedMetadata.model_validate(current.effective_payload)
            result = self.editor.merge_episode_table(
                _sdk_metadata(normalized),
                EpisodeTableDocument.from_bytes(content.encode("utf-8")),
            )
            if (
                result.identity.provider_id != item.provider_key
                or result.identity.external_id != item.external_id
                or result.identity.media_kind.value != item.kind
            ):
                raise ValueError("manual_identity_mismatch")
            raw_payload = result.raw_payload.model_dump(mode="json")["data"]
            if not isinstance(raw_payload, dict):
                raise ValueError("manual_raw_payload_invalid")
            self.catalog.add_revision(
                item,
                RevisionInput(
                    normalized=_legacy_metadata(result.metadata),
                    raw_payload=raw_payload,
                ),
            )
            return item
        except Exception:
            self.catalog.session.rollback()
            raise


__all__ = ["ManualCatalogService"]
