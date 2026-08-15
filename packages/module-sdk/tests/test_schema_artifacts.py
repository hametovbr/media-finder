"""Deterministic language-neutral SDK schema artifacts."""

from __future__ import annotations

import json
from pathlib import Path

from media_finder_sdk import generate_schema_artifacts

ROOT = Path(__file__).parents[3]
SCHEMA_ROOT = ROOT / "schemas" / "module-sdk" / "v1"
EXPECTED = {
    "download.schema.json",
    "error.schema.json",
    "metadata.schema.json",
    "module-manifest.schema.json",
    "release.schema.json",
    "retention.schema.json",
}


def test_schema_generation_is_byte_stable_and_checked_in() -> None:
    first = generate_schema_artifacts()
    second = generate_schema_artifacts()

    assert set(first) == EXPECTED
    assert first == second
    for filename, generated in first.items():
        assert generated.endswith(b"\n")
        assert (SCHEMA_ROOT / filename).read_bytes() == generated
        parsed = json.loads(generated)
        assert parsed["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert parsed["$id"] == f"https://schemas.media-finder.dev/module-sdk/v1/{filename}"
        assert parsed["title"].startswith("Media Finder")
        assert b"media_finder_core" not in generated
        assert b"sqlalchemy" not in generated.lower()


def test_schemas_preserve_semantic_module_boundaries() -> None:
    schemas = {
        filename: json.loads(payload) for filename, payload in generate_schema_artifacts().items()
    }

    manifest = schemas["module-manifest.schema.json"]
    assert set(manifest["required"]) >= {
        "module_id",
        "module_kind",
        "module_version",
        "sdk_compatibility",
        "contract_version",
        "capabilities",
        "translation_keys",
    }
    assert set(manifest["properties"]["module_kind"]["enum"]) == {
        "metadata-provider",
        "release-provider",
        "download-client",
    }

    metadata_definitions = schemas["metadata.schema.json"]["$defs"]
    assert {
        "MetadataEditResult",
        "MetadataIdentity",
        "MetadataImportDocument",
        "MetadataSearchQuery",
        "NormalizedMetadata",
    } <= set(metadata_definitions)
    assert metadata_definitions["MetadataImportDocument"]["writeOnly"] is True
    assert metadata_definitions["EpisodeTableDocument"]["writeOnly"] is True
    release_definitions = schemas["release.schema.json"]["$defs"]
    assert release_definitions["PrivateReleaseSelection"]["writeOnly"] is True
    assert release_definitions["TorrentArtifact"]["maxLength"] > 0
