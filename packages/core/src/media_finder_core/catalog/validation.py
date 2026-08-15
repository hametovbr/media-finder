"""Validation shared by catalog metadata application services."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from media_finder_sdk import (
    MetadataEditResult,
    MetadataIdentity,
    MetadataSearchResult,
    NormalizedMetadata,
    ProviderPayload,
    RetentionAction,
    RetentionPolicy,
)
from media_finder_sdk.errors import JsonValue
from pydantic import ValidationError

from .models import CatalogIdentity, RevisionDraft

OVERRIDABLE_FIELDS = frozenset(
    {
        "titles",
        "original_title",
        "year",
        "plot",
        "release_date",
        "runtime_minutes",
        "ratings",
        "genres",
        "tags",
        "countries",
        "studios",
        "people",
        "artwork",
        "seasons",
        "completeness",
        "structural_quality",
    }
)


def catalog_identity(identity: MetadataIdentity) -> CatalogIdentity:
    return CatalogIdentity(
        provider_id=identity.provider_id,
        external_id=identity.external_id,
        media_kind=identity.media_kind,
    )


def validate_search_result(result: object, *, expected_provider_id: str) -> MetadataSearchResult:
    try:
        validated = MetadataSearchResult.model_validate(_public_payload(result))
    except (AttributeError, TypeError, ValueError, ValidationError) as error:
        raise ValueError("provider_output_invalid") from error
    if validated.provider_id != expected_provider_id:
        raise ValueError("provider_identity_mismatch")
    return validated


def validate_normalized(
    value: object,
    *,
    identity: MetadataIdentity,
) -> NormalizedMetadata:
    try:
        normalized = NormalizedMetadata.model_validate(_public_payload(value))
    except (AttributeError, TypeError, ValueError, ValidationError) as error:
        raise ValueError("provider_output_invalid") from error
    provenance = normalized.provenance
    if (
        normalized.kind is not identity.media_kind
        or provenance.provider_id != identity.provider_id
        or provenance.external_id != identity.external_id
        or provenance.locale != identity.locale
    ):
        raise ValueError("provider_identity_mismatch")
    return normalized


def validate_provider_payload(value: object) -> ProviderPayload:
    try:
        return ProviderPayload.model_validate(_public_payload(value))
    except (AttributeError, TypeError, ValueError, ValidationError) as error:
        raise ValueError("provider_output_invalid") from error


def validate_retention_action(value: object) -> RetentionAction:
    try:
        return RetentionAction.model_validate(_public_payload(value))
    except (AttributeError, TypeError, ValueError, ValidationError) as error:
        raise ValueError("provider_output_invalid") from error


def validate_retention_policy(value: object) -> RetentionPolicy:
    try:
        return RetentionPolicy.model_validate(_public_payload(value))
    except (AttributeError, TypeError, ValueError, ValidationError) as error:
        raise ValueError("provider_output_invalid") from error


def validate_edit_result(value: object) -> MetadataEditResult:
    try:
        result = MetadataEditResult.model_validate(_public_payload(value))
    except (AttributeError, TypeError, ValueError, ValidationError) as error:
        raise ValueError("provider_output_invalid") from error
    validate_normalized(result.metadata, identity=result.identity)
    return result


def revision_draft(
    *,
    raw_payload: ProviderPayload | None,
    normalized: NormalizedMetadata,
    retention: RetentionPolicy,
    created_at: datetime,
    overrides: Mapping[str, JsonValue] | None = None,
) -> RevisionDraft:
    selected_overrides = dict(overrides or {})
    unknown = set(selected_overrides) - OVERRIDABLE_FIELDS
    if unknown:
        raise ValueError("metadata_override_unsupported")
    try:
        effective = NormalizedMetadata.model_validate(
            normalized.model_dump(mode="json") | selected_overrides
        )
    except ValidationError as error:
        raise ValueError("metadata_override_invalid") from error
    return RevisionDraft(
        raw_payload=raw_payload,
        normalized=normalized,
        overrides=selected_overrides,
        effective=effective,
        refresh_after=retention.refresh_after,
        expires_at=retention.expires_at,
        created_at=created_at,
    )


def _public_payload(value: object) -> object:
    dump = getattr(value, "model_dump", None)
    if not callable(dump):
        raise TypeError("public_model_required")
    return dump(mode="json")


__all__ = [
    "OVERRIDABLE_FIELDS",
    "catalog_identity",
    "revision_draft",
    "validate_edit_result",
    "validate_normalized",
    "validate_provider_payload",
    "validate_retention_action",
    "validate_retention_policy",
    "validate_search_result",
]
