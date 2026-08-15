"""Deterministic JSON Schema artifacts for SDK version one."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType

from .common import PublicModel
from .errors import ModuleErrorData
from .manifest import ModuleManifest
from .types import (
    CorrelationResult,
    DownloadDestination,
    EpisodeTableDocument,
    ExportWarning,
    MagnetArtifact,
    MetadataEditResult,
    MetadataIdentity,
    MetadataImportDocument,
    MetadataSearchQuery,
    MetadataSearchResult,
    NormalizedMetadata,
    ProviderPayload,
    ReleaseSearchQuery,
    RetentionAction,
    RetentionPolicy,
    RetentionSubject,
    SafeReleaseSnapshot,
    SubmissionResult,
)

SCHEMA_BASE_ID = "https://schemas.media-finder.dev/module-sdk/v1"


class _MetadataContract(PublicModel):
    identity: MetadataIdentity
    search_query: MetadataSearchQuery
    search_result: MetadataSearchResult
    provider_payload: ProviderPayload
    normalized_metadata: NormalizedMetadata
    edit_result: MetadataEditResult


class _RetentionContract(PublicModel):
    policy: RetentionPolicy
    subject: RetentionSubject
    action: RetentionAction
    export_warning: ExportWarning | None


class _ReleaseContract(PublicModel):
    search_query: ReleaseSearchQuery
    safe_snapshot: SafeReleaseSnapshot
    magnet_artifact: MagnetArtifact


class _DownloadContract(PublicModel):
    destination: DownloadDestination
    magnet_artifact: MagnetArtifact
    submission: SubmissionResult
    correlation: CorrelationResult


def _root_schema(model: type[PublicModel], filename: str, title: str) -> dict[str, object]:
    schema = model.model_json_schema(mode="serialization")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"{SCHEMA_BASE_ID}/{filename}"
    schema["title"] = title
    return schema


def _private_release_definitions() -> dict[str, object]:
    return {
        "PrivateReleaseSelection": {
            "contentEncoding": "base64",
            "description": "Provider-private bounded selection; never exposed to browsers.",
            "maxLength": 87384,
            "minLength": 4,
            "type": "string",
            "writeOnly": True,
        },
        "TorrentArtifact": {
            "contentEncoding": "base64",
            "description": "Bounded in-memory torrent bytes; never persisted or exposed.",
            "maxLength": 27962028,
            "minLength": 4,
            "type": "string",
            "writeOnly": True,
        },
    }


def _private_metadata_definitions() -> dict[str, object]:
    return {
        MetadataImportDocument.__name__: {
            "contentEncoding": "base64",
            "description": "Bounded provider-owned import document; never exposed to browsers.",
            "maxLength": 1398104,
            "minLength": 4,
            "type": "string",
            "writeOnly": True,
        },
        EpisodeTableDocument.__name__: {
            "contentEncoding": "base64",
            "description": "Bounded provider-owned episode table; never exposed to browsers.",
            "maxLength": 1398104,
            "minLength": 4,
            "type": "string",
            "writeOnly": True,
        },
    }


def _add_private_release_definitions(schema: dict[str, object]) -> None:
    definitions = schema.get("$defs")
    if not isinstance(definitions, dict):
        definitions = {}
        schema["$defs"] = definitions
    definitions.update(_private_release_definitions())


def _add_private_metadata_definitions(schema: dict[str, object]) -> None:
    definitions = schema.get("$defs")
    if not isinstance(definitions, dict):
        definitions = {}
        schema["$defs"] = definitions
    definitions.update(_private_metadata_definitions())


def _schemas() -> dict[str, dict[str, object]]:
    manifest = _root_schema(
        ModuleManifest,
        "module-manifest.schema.json",
        "Media Finder Module Manifest v1",
    )
    definitions = manifest.get("$defs")
    properties = manifest.get("properties")
    if isinstance(definitions, dict) and isinstance(properties, dict):
        module_kind = definitions.pop("ModuleKind", None)
        if isinstance(module_kind, dict):
            properties["module_kind"] = module_kind

    release = _root_schema(
        _ReleaseContract,
        "release.schema.json",
        "Media Finder Release Provider Contract v1",
    )
    _add_private_release_definitions(release)
    download = _root_schema(
        _DownloadContract,
        "download.schema.json",
        "Media Finder Download Client Contract v1",
    )
    _add_private_release_definitions(download)
    metadata = _root_schema(
        _MetadataContract,
        "metadata.schema.json",
        "Media Finder Metadata Provider Contract v1",
    )
    _add_private_metadata_definitions(metadata)

    return {
        "download.schema.json": download,
        "error.schema.json": _root_schema(
            ModuleErrorData,
            "error.schema.json",
            "Media Finder Module Error Contract v1",
        ),
        "metadata.schema.json": metadata,
        "module-manifest.schema.json": manifest,
        "release.schema.json": release,
        "retention.schema.json": _root_schema(
            _RetentionContract,
            "retention.schema.json",
            "Media Finder Metadata Retention Contract v1",
        ),
    }


def generate_schema_artifacts() -> Mapping[str, bytes]:
    """Return byte-stable version-one schema artifacts keyed by filename."""

    generated = {
        filename: (json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        )
        for filename, schema in sorted(_schemas().items())
    }
    return MappingProxyType(generated)


def write_schema_artifacts(destination: Path) -> None:
    """Regenerate checked schema artifacts for review and CI drift checks."""

    destination.mkdir(parents=True, exist_ok=True)
    for filename, content in generate_schema_artifacts().items():
        (destination / filename).write_bytes(content)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    write_schema_artifacts(arguments.output)


if __name__ == "__main__":
    main()


__all__ = ["SCHEMA_BASE_ID", "generate_schema_artifacts", "write_schema_artifacts"]
