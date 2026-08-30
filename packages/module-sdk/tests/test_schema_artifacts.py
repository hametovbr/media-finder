"""Deterministic language-neutral SDK schema artifacts."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from media_finder_sdk import SDK_VERSION, generate_schema_artifacts

ROOT = Path(__file__).parents[3]
SCHEMA_ROOT = ROOT / "schemas" / "module-sdk" / "v1"
EXPECTED = {
    "conformance.schema.json",
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
    assert manifest["properties"]["module_id"]["maxLength"] == 100

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
    provider_data = metadata_definitions["ProviderPayload"]["properties"]["data"]
    assert provider_data["x-media-finder-max-canonical-json-bytes"] == 2 * 1024 * 1024
    assert provider_data["x-media-finder-max-depth"] == 32
    assert provider_data["x-media-finder-max-nodes"] == 100_000
    assert provider_data["type"] == "object"
    assert provider_data["additionalProperties"] == {"$ref": "#/$defs/JsonValue"}
    release_definitions = schemas["release.schema.json"]["$defs"]
    assert release_definitions["PrivateReleaseSelection"]["writeOnly"] is True
    assert release_definitions["TorrentArtifact"]["maxLength"] > 0


def test_metadata_search_preview_contract_is_optional_and_version_one() -> None:
    schemas = {
        filename: json.loads(payload) for filename, payload in generate_schema_artifacts().items()
    }
    metadata_result = schemas["metadata.schema.json"]["$defs"]["MetadataSearchResult"]
    serialized_result = schemas["conformance.schema.json"]["$defs"]["MetadataSearchResult"]

    assert metadata_result == serialized_result
    assert metadata_result["additionalProperties"] is False
    assert set(metadata_result["properties"]) == {
        "description",
        "external_id",
        "locale",
        "media_kind",
        "poster_url",
        "provider_id",
        "title",
        "year",
    }
    assert "description" not in metadata_result["required"]
    assert "poster_url" not in metadata_result["required"]
    assert metadata_result["properties"]["description"] == {
        "anyOf": [{"type": "string"}, {"type": "null"}],
        "default": None,
        "title": "Description",
    }
    poster_url = metadata_result["properties"]["poster_url"]
    assert poster_url["default"] is None
    assert poster_url["anyOf"][0]["format"] == "uri"
    assert poster_url["anyOf"][1] == {"type": "null"}

    assert str(SDK_VERSION) == "1.0.0"
    for manifest_path in (
        ROOT / "packages/modules/metadata-manual/src/media_finder_metadata_manual/module.toml",
        ROOT / "packages/modules/metadata-tmdb/src/media_finder_metadata_tmdb/module.toml",
    ):
        manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["sdk_compatibility"] == ">=1,<2"
        assert manifest["contract_version"] == "1"


def test_conformance_schema_is_discriminated_and_never_serializes_private_values() -> None:
    schema = json.loads(generate_schema_artifacts()["conformance.schema.json"])

    assert schema["discriminator"] == {
        "mapping": {
            "download-client": "#/$defs/SerializedDownloadClientConformance",
            "metadata-provider": "#/$defs/SerializedMetadataProviderConformance",
            "release-provider": "#/$defs/SerializedReleaseProviderConformance",
        },
        "propertyName": "module_kind",
    }
    definitions = schema["$defs"]
    assert {
        "ArtifactDescriptor",
        "SerializedDownloadClientConformance",
        "SerializedMetadataProviderConformance",
        "SerializedReleaseProviderConformance",
    } <= set(definitions)
    artifact = definitions["ArtifactDescriptor"]
    assert set(artifact["properties"]) == {"byte_length", "kind", "sha256"}
    assert artifact["allOf"] == [
        {
            "if": {"properties": {"kind": {"const": "magnet"}}, "required": ["kind"]},
            "then": {"properties": {"byte_length": {"maximum": 8192}}},
        },
        {
            "if": {"properties": {"kind": {"const": "torrent"}}, "required": ["kind"]},
            "then": {"properties": {"byte_length": {"maximum": 20 * 1024 * 1024}}},
        },
    ]
    snapshot = definitions["SerializedSafeReleaseSnapshot"]
    assert snapshot["properties"]["guid"]["anyOf"][0] == {
        "maxLength": 255,
        "minLength": 1,
        "pattern": "^[A-Za-z0-9._:-]+$",
        "type": "string",
    }

    schema_without_probe_declaration = dict(schema)
    schema_without_probe_declaration["$defs"] = dict(schema["$defs"])
    schema_without_probe_declaration["$defs"].pop("RedactionProbeSet")
    rendered = json.dumps(schema_without_probe_declaration, sort_keys=True).casefold()
    for forbidden in (
        "environment_values",
        "private_selection",
        "artifact_body",
        "torrent_bytes",
        "magnet_uri",
    ):
        assert forbidden not in rendered
