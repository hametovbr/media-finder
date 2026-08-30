"""Language-neutral serialized module conformance contracts."""

from __future__ import annotations

import json

import pytest
from media_finder_sdk import (
    SerializedDownloadClientConformance,
    SerializedMetadataProviderConformance,
    SerializedReleaseProviderConformance,
    parse_serialized_conformance_fixture,
)
from pydantic import ValidationError


def _common(module_kind: str) -> dict[str, object]:
    return {
        "schema_version": "1",
        "module_id": "fixture",
        "module_kind": module_kind,
        "module_version": "0.1.0",
        "sdk_compatibility": ">=1,<2",
        "contract_version": "1",
        "manifest_sha256": "a" * 64,
        "capabilities": ["fixture"],
        "environment": [],
        "missing_configuration": {"applicable": False},
        "stable_failures": [
            {
                "operation": "validate",
                "error": {
                    "category": "unavailable",
                    "code": "fixture_unavailable",
                    "safe_details": {},
                },
            }
        ],
        "redaction_markers": [
            "artifact-body",
            "environment-values",
            "private-selection",
        ],
        "redaction_probes": {
            "artifact_body": "mf-redaction-probe-artifact-body",
            "credential": "mf-redaction-probe-credential",
            "environment_value": "mf-redaction-probe-environment-value",
            "private_selection": "mf-redaction-probe-private-selection",
        },
    }


def _release_fixture() -> dict[str, object]:
    return _common("release-provider") | {
        "success": {
            "query": {"query": "Fixture", "limit": 1},
            "results": [
                {
                    "selection_ref": "fixture-magnet",
                    "snapshot": {"title": "Fixture", "indexer": "Fixture"},
                }
            ],
            "resolved_artifacts": [
                {
                    "selection_ref": "fixture-magnet",
                    "artifact": {"kind": "magnet", "byte_length": 42, "sha256": "b" * 64},
                }
            ],
        }
    }


def _metadata_fixture() -> dict[str, object]:
    return _common("metadata-provider") | {
        "success": {
            "query": {"query": "Fixture", "locale": "en", "limit": 1},
            "results": [
                {
                    "provider_id": "fixture",
                    "external_id": "1",
                    "media_kind": "movie",
                    "title": "Fixture",
                    "locale": "en",
                }
            ],
            "identity": {
                "provider_id": "fixture",
                "external_id": "1",
                "media_kind": "movie",
                "locale": "en",
            },
            "normalized": {
                "kind": "movie",
                "titles": {"en": "Fixture"},
                "provenance": {
                    "provider_id": "fixture",
                    "external_id": "1",
                    "locale": "en",
                },
            },
            "retention": {
                "created_at": "2026-01-01T00:00:00Z",
                "now": "2026-01-01T00:00:00Z",
                "policy": {},
                "action": {"kind": "none", "mandatory": False},
                "warning": None,
            },
        }
    }


def test_serialized_conformance_parser_discriminates_all_module_kinds() -> None:
    metadata = _metadata_fixture()
    release = _release_fixture()
    download = _common("download-client") | {
        "success": {
            "destinations": [{"key": "fixture", "label": "Fixture"}],
            "artifacts": [
                {"kind": "magnet", "byte_length": 42, "sha256": "b" * 64},
            ],
            "destination": "fixture",
            "correlation": "mf-acq-47e26ca2-f393-4a00-b33a-902d41d49714",
            "submission": {
                "accepted": True,
                "correlation": "mf-acq-47e26ca2-f393-4a00-b33a-902d41d49714",
            },
            "lookup": {
                "found": True,
                "correlation": "mf-acq-47e26ca2-f393-4a00-b33a-902d41d49714",
            },
        }
    }

    parsed_metadata = parse_serialized_conformance_fixture(json.dumps(metadata).encode())
    assert isinstance(parsed_metadata, SerializedMetadataProviderConformance)
    assert parsed_metadata.success.results[0].description is None
    assert parsed_metadata.success.results[0].poster_url is None
    assert isinstance(
        parse_serialized_conformance_fixture(json.dumps(release).encode()),
        SerializedReleaseProviderConformance,
    )
    assert isinstance(
        parse_serialized_conformance_fixture(json.dumps(download).encode()),
        SerializedDownloadClientConformance,
    )


def test_serialized_metadata_previews_accept_valid_values_and_reject_invalid_urls() -> None:
    fixture = _metadata_fixture()
    result = fixture["success"]["results"][0]  # type: ignore[index]
    result["description"] = "A serialized preview."  # type: ignore[index]
    result["poster_url"] = "https://images.example.test/posters/fixture.jpg"  # type: ignore[index]

    parsed = parse_serialized_conformance_fixture(json.dumps(fixture).encode())

    assert isinstance(parsed, SerializedMetadataProviderConformance)
    assert parsed.success.results[0].description == "A serialized preview."
    assert str(parsed.success.results[0].poster_url) == (
        "https://images.example.test/posters/fixture.jpg"
    )

    result["poster_url"] = "not a URL"  # type: ignore[index]
    with pytest.raises(ValidationError):
        parse_serialized_conformance_fixture(json.dumps(fixture).encode())


@pytest.mark.parametrize(
    ("forbidden_key", "value"),
    (
        ("environment_values", {"TOKEN": "secret"}),
        ("private_selection", "opaque-body"),
        ("artifact_body", "torrent-body"),
    ),
)
def test_serialized_conformance_rejects_private_value_surfaces(
    forbidden_key: str,
    value: object,
) -> None:
    fixture = _common("release-provider") | {
        "success": {
            "query": {"query": "Fixture", "limit": 1},
            "results": [
                {
                    "selection_ref": "fixture",
                    "snapshot": {"title": "Fixture", "indexer": "Fixture"},
                }
            ],
            "resolved_artifacts": [
                {
                    "selection_ref": "fixture",
                    "artifact": {"kind": "torrent", "byte_length": 10, "sha256": "c" * 64},
                }
            ],
        },
        forbidden_key: value,
    }

    with pytest.raises(ValidationError):
        parse_serialized_conformance_fixture(json.dumps(fixture).encode())


def test_serialized_module_version_accepts_the_manifest_full_semver_contract() -> None:
    fixture = _release_fixture()
    fixture["module_version"] = "1.2.3-rc.1+build.5"

    parsed = parse_serialized_conformance_fixture(json.dumps(fixture).encode())

    assert parsed.module_version == "1.2.3-rc.1+build.5"


@pytest.mark.parametrize(
    ("kind", "byte_length"),
    (("magnet", 8193), ("torrent", 20 * 1024 * 1024 + 1)),
)
def test_serialized_artifact_descriptors_enforce_kind_specific_bounds(
    kind: str,
    byte_length: int,
) -> None:
    fixture = _release_fixture()
    fixture["success"]["resolved_artifacts"][0]["artifact"] = {  # type: ignore[index]
        "kind": kind,
        "byte_length": byte_length,
        "sha256": "b" * 64,
    }

    with pytest.raises(ValidationError):
        parse_serialized_conformance_fixture(json.dumps(fixture).encode())


def test_serialized_selection_refs_are_bounded() -> None:
    fixture = _release_fixture()
    fixture["success"]["results"][0]["selection_ref"] = "x" * 129  # type: ignore[index]

    with pytest.raises(ValidationError):
        parse_serialized_conformance_fixture(json.dumps(fixture).encode())


@pytest.mark.parametrize(
    "guid",
    (
        "x" * 256,
        "https://indexer.example/release",
        "credential-token-123",
        "release%2Fsecret",
    ),
)
def test_serialized_release_guid_is_canonical_and_not_credential_like(guid: str) -> None:
    fixture = _release_fixture()
    fixture["success"]["results"][0]["snapshot"]["guid"] = guid  # type: ignore[index]

    with pytest.raises(ValidationError):
        parse_serialized_conformance_fixture(json.dumps(fixture).encode())


@pytest.mark.parametrize(
    "source_page_url",
    (
        "https://media.themoviedb.org/releases/fixture-1",
        "https://indexer.example.test/releases/fixture-1",
        "https://8.8.8.8/releases/fixture-1",
        "https://[2606:4700:4700::1111]/releases/fixture-1",
    ),
)
def test_serialized_public_source_page_accepts_public_hosts_and_normalized_safe_paths(
    source_page_url: str,
) -> None:
    fixture = _release_fixture()
    fixture["success"]["results"][0]["snapshot"]["source_page_url"] = source_page_url  # type: ignore[index]

    parsed = parse_serialized_conformance_fixture(json.dumps(fixture).encode())

    assert str(parsed.success.results[0].snapshot.source_page_url) == source_page_url


@pytest.mark.parametrize(
    "source_page_url",
    (
        "https://user:pass@indexer.example/releases/1",
        "https://indexer.example/releases/1?passkey=secret",
        "https://indexer.example/releases/1#secret",
        "http://127.0.0.1/releases/1",
        "http://192.168.1.2/releases/1",
        "http://localhost/releases/1",
        "http://intranet/releases/1",
        "http://printer.local/releases/1",
        "http://service.localhost/releases/1",
        "http://service.internal/releases/1",
        "http://nas.lan/releases/1",
        "http://service.test/releases/1",
        "http://example.test/releases/1",
        "http://service.invalid/releases/1",
        "http://service.example/releases/1",
        "http://service.home/releases/1",
        "http://service.home.arpa/releases/1",
        "http://192.0.2.1/releases/1",
        "http://198.18.0.1/releases/1",
        "http://198.51.100.1/releases/1",
        "http://203.0.113.1/releases/1",
        "http://224.0.0.1/releases/1",
        "http://127.1/releases/1",
        "http://0177.0.0.1/releases/1",
        "http://0x7f.0.0.1/releases/1",
        "http://[2001:db8::1]/releases/1",
        "http://[fe80::1]/releases/1",
        "http://[fc00::1]/releases/1",
        "http://[ff02::1]/releases/1",
        "https://indexer.example/releases/token-secret",
        "https://indexer.example/releases/%2e%2e/private",
        "ftp://media.themoviedb.org/releases/1",
        " https://media.themoviedb.org/releases/1",
        "https://media.themoviedb.org/releases//1",
        "https://media.themoviedb.org/releases/../private",
        "https://media.themoviedb.org/releases/./private",
        "https://media.themoviedb.org/releases/1?",
        "https://media.themoviedb.org/releases/1#",
        "https://@media.themoviedb.org/releases/1",
    ),
)
def test_serialized_public_source_page_rejects_unsafe_components(
    source_page_url: str,
) -> None:
    fixture = _release_fixture()
    fixture["success"]["results"][0]["snapshot"]["source_page_url"] = source_page_url  # type: ignore[index]

    with pytest.raises(ValidationError):
        parse_serialized_conformance_fixture(json.dumps(fixture).encode())
