"""Serializable module conformance values shared across implementation languages."""

from __future__ import annotations

import ipaddress
import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, HttpUrl, TypeAdapter, field_validator, model_validator

from .common import PublicModel
from .errors import ModuleErrorData
from .manifest import SEMVER_PATTERN, EnvironmentVariableSpec
from .types import (
    CorrelationResult,
    DownloadDestination,
    ExportWarning,
    MetadataIdentity,
    MetadataSearchQuery,
    MetadataSearchResult,
    NormalizedMetadata,
    ReleaseSearchQuery,
    RetentionAction,
    RetentionPolicy,
    SubmissionResult,
)

type RedactionMarker = Literal[
    "artifact-body",
    "environment-values",
    "private-selection",
]
_CREDENTIAL_MARKER = re.compile(
    r"(?:api[-_]?key|bearer|credential|passkey|password|secret|session|token)",
    re.IGNORECASE,
)
_PUBLIC_PATH = re.compile(r"^/(?:[A-Za-z0-9._~-]+/)*[A-Za-z0-9._~-]*$")
_DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_SYNTHETIC_DOCUMENTATION_SUFFIX = ".example.test"
_NON_PUBLIC_DNS_SUFFIXES = (
    "alt",
    "example",
    "home",
    "home.arpa",
    "internal",
    "invalid",
    "lan",
    "local",
    "localdomain",
    "localhost",
    "onion",
    "private",
    "test",
)
_NON_PUBLIC_IPV4_NETWORKS = tuple(
    ipaddress.ip_network(value)
    for value in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.0.2.0/24",
        "192.88.99.0/24",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "224.0.0.0/3",
    )
)
_PUBLIC_IPV6_NETWORK = ipaddress.ip_network("2000::/3")
_NON_PUBLIC_IPV6_NETWORKS = tuple(
    ipaddress.ip_network(value)
    for value in (
        "2001::/23",
        "2001:db8::/32",
        "2002::/16",
    )
)


class MissingConfigurationCase(PublicModel):
    applicable: Literal[True]
    omitted: tuple[Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]*$")], ...] = Field(min_length=1)
    error: ModuleErrorData


class ConfigurationFreeCase(PublicModel):
    applicable: Literal[False]


type SerializedMissingConfiguration = Annotated[
    MissingConfigurationCase | ConfigurationFreeCase,
    Field(discriminator="applicable"),
]


class StableFailureCase(PublicModel):
    operation: Annotated[str, Field(pattern=r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")]
    error: ModuleErrorData


class ArtifactDescriptor(PublicModel):
    """Safe digest-and-size descriptor; it never carries an artifact body."""

    kind: Literal["magnet", "torrent"]
    byte_length: int = Field(
        ge=1,
        le=20 * 1024 * 1024,
        description=("UTF-8 byte length of a magnet URI or raw byte length of a torrent payload."),
    )
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

    @model_validator(mode="after")
    def enforce_kind_specific_bound(self) -> ArtifactDescriptor:
        if self.kind == "magnet" and self.byte_length > 8192:
            raise ValueError("serialized_magnet_artifact_too_large")
        return self


class RedactionProbeSet(PublicModel):
    artifact_body: Annotated[str, Field(pattern=r"^mf-redaction-probe-[a-z-]+$")]
    credential: Annotated[str, Field(pattern=r"^mf-redaction-probe-[a-z-]+$")]
    environment_value: Annotated[str, Field(pattern=r"^mf-redaction-probe-[a-z-]+$")]
    private_selection: Annotated[str, Field(pattern=r"^mf-redaction-probe-[a-z-]+$")]

    @model_validator(mode="after")
    def require_unique_probes(self) -> RedactionProbeSet:
        if len(set(self.model_dump().values())) != 4:
            raise ValueError("serialized_redaction_probe_duplicate")
        return self


class MetadataRetentionCase(PublicModel):
    created_at: datetime
    now: datetime
    policy: RetentionPolicy
    action: RetentionAction
    warning: ExportWarning | None


class MetadataEditorCase(PublicModel):
    imported_identity: MetadataIdentity
    merged_episode_count: int = Field(ge=1, le=100_000)


class MetadataSuccessCase(PublicModel):
    query: MetadataSearchQuery
    results: tuple[MetadataSearchResult, ...] = Field(min_length=1, max_length=100)
    identity: MetadataIdentity
    normalized: NormalizedMetadata
    retention: MetadataRetentionCase
    editor: MetadataEditorCase | None = None

    @model_validator(mode="after")
    def require_consistent_identity_and_bounds(self) -> MetadataSuccessCase:
        if len(self.results) > self.query.limit:
            raise ValueError("serialized_metadata_result_limit_exceeded")
        if not any(
            result.provider_id == self.identity.provider_id
            and result.external_id == self.identity.external_id
            and result.media_kind is self.identity.media_kind
            and result.locale == self.identity.locale
            for result in self.results
        ):
            raise ValueError("serialized_metadata_identity_result_missing")
        provenance = self.normalized.provenance
        if (
            self.normalized.kind is not self.identity.media_kind
            or provenance.provider_id != self.identity.provider_id
            or provenance.external_id != self.identity.external_id
            or provenance.locale != self.identity.locale
        ):
            raise ValueError("serialized_metadata_identity_mismatch")
        if self.editor is not None and self.editor.imported_identity != self.identity:
            raise ValueError("serialized_metadata_editor_identity_mismatch")
        return self


class SerializedSafeReleaseSnapshot(PublicModel):
    title: Annotated[str, Field(min_length=1, max_length=1000)]
    indexer: Annotated[str, Field(min_length=1, max_length=300)]
    guid: (
        Annotated[
            str,
            Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9._:-]+$"),
        ]
        | None
    ) = None
    infohash: (
        Annotated[
            str,
            Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$"),
        ]
        | None
    ) = None
    source_page_url: HttpUrl | None = None

    @field_validator("guid")
    @classmethod
    def reject_credential_like_guid(cls, value: str | None) -> str | None:
        if value is not None and not is_safe_release_guid(value):
            raise ValueError("serialized_release_guid_sensitive")
        return value

    @field_validator("source_page_url", mode="before")
    @classmethod
    def reject_unsafe_raw_source(cls, value: object) -> object:
        if value is not None and not is_safe_public_source_page(str(value)):
            raise ValueError("serialized_source_page_url_unsafe")
        return value


def is_safe_public_source_page(value: str) -> bool:
    """Validate the language-neutral public source-page contract."""

    from urllib.parse import urlsplit

    if value != value.strip() or any(ord(character) < 32 for character in value):
        return False
    if "%" in value or "\\" in value or ";" in value or "?" in value or "#" in value:
        return False
    if re.search(r"(?:^|/)\.{1,2}(?:/|$)", value) is not None:
        return False
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        path = parsed.path or "/"
        if (
            parsed.scheme not in {"http", "https"}
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or not _is_public_host(host)
            or _PUBLIC_PATH.fullmatch(path) is None
            or any(
                segment in {".", ".."} or _CREDENTIAL_MARKER.search(segment) is not None
                for segment in path.split("/")
                if segment
            )
        ):
            return False
        _ = parsed.port
    except (UnicodeError, ValueError):
        return False
    return True


def is_safe_release_guid(value: str) -> bool:
    """Validate the language-neutral safe release GUID contract."""

    return (
        0 < len(value) <= 255
        and re.fullmatch(r"[A-Za-z0-9._:-]+", value) is not None
        and _CREDENTIAL_MARKER.search(value) is None
    )


def _is_public_host(host: str) -> bool:
    normalized = host.strip("[]").rstrip(".").casefold()
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        try:
            dns_name = normalized.encode("idna").decode("ascii")
        except UnicodeError:
            return False
        labels = dns_name.split(".")
        if (
            len(dns_name) > 253
            or len(labels) < 2
            or labels[-1].isdigit()
            or not all(_DNS_LABEL.fullmatch(label) for label in labels)
        ):
            return False
        # Only repository fixtures may use this documented synthetic namespace.
        if dns_name.endswith(_SYNTHETIC_DOCUMENTATION_SUFFIX):
            return dns_name != _SYNTHETIC_DOCUMENTATION_SUFFIX.removeprefix(".")
        return not any(
            dns_name == suffix or dns_name.endswith(f".{suffix}")
            for suffix in _NON_PUBLIC_DNS_SUFFIXES
        )
    if isinstance(address, ipaddress.IPv4Address):
        return not any(address in network for network in _NON_PUBLIC_IPV4_NETWORKS)
    return address in _PUBLIC_IPV6_NETWORK and not any(
        address in network for network in _NON_PUBLIC_IPV6_NETWORKS
    )


class SerializedReleaseResult(PublicModel):
    selection_ref: Annotated[
        str,
        Field(max_length=128, pattern=r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$"),
    ]
    snapshot: SerializedSafeReleaseSnapshot


class SerializedResolvedArtifact(PublicModel):
    selection_ref: Annotated[
        str,
        Field(max_length=128, pattern=r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$"),
    ]
    artifact: ArtifactDescriptor


class ReleaseSuccessCase(PublicModel):
    query: ReleaseSearchQuery
    results: tuple[SerializedReleaseResult, ...] = Field(min_length=1, max_length=100)
    resolved_artifacts: tuple[SerializedResolvedArtifact, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def require_bounded_linked_results(self) -> ReleaseSuccessCase:
        if len(self.results) > self.query.limit:
            raise ValueError("serialized_release_result_limit_exceeded")
        references = tuple(result.selection_ref for result in self.results)
        if len(references) != len(set(references)):
            raise ValueError("serialized_release_selection_ref_duplicate")
        resolved = tuple(item.selection_ref for item in self.resolved_artifacts)
        if len(resolved) != len(set(resolved)) or not set(resolved).issubset(references):
            raise ValueError("serialized_release_artifact_ref_invalid")
        return self


class DownloadSuccessCase(PublicModel):
    destinations: tuple[DownloadDestination, ...] = Field(min_length=1, max_length=100)
    artifacts: tuple[ArtifactDescriptor, ...] = Field(min_length=1, max_length=2)
    destination: Annotated[str, Field(min_length=1, max_length=500)]
    correlation: Annotated[str, Field(min_length=1, max_length=200)]
    submission: SubmissionResult
    lookup: CorrelationResult

    @model_validator(mode="after")
    def require_consistent_submission(self) -> DownloadSuccessCase:
        if self.destination not in {destination.key for destination in self.destinations}:
            raise ValueError("serialized_download_destination_missing")
        if (
            self.submission.correlation != self.correlation
            or self.lookup.correlation != self.correlation
        ):
            raise ValueError("serialized_download_correlation_mismatch")
        kinds = tuple(artifact.kind for artifact in self.artifacts)
        if len(kinds) != len(set(kinds)):
            raise ValueError("serialized_download_artifact_duplicate")
        return self


class _SerializedConformanceBase(PublicModel):
    schema_version: Literal["1"]
    module_id: Annotated[
        str,
        Field(max_length=100, pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$"),
    ]
    module_version: Annotated[str, Field(pattern=SEMVER_PATTERN)]
    sdk_compatibility: Annotated[str, Field(min_length=1, max_length=100)]
    contract_version: Annotated[str, Field(min_length=1, max_length=32)]
    manifest_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    capabilities: tuple[Annotated[str, Field(pattern=r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")], ...] = (
        Field(min_length=1)
    )
    environment: tuple[EnvironmentVariableSpec, ...]
    missing_configuration: SerializedMissingConfiguration
    stable_failures: tuple[StableFailureCase, ...] = Field(min_length=1)
    redaction_markers: tuple[RedactionMarker, ...] = Field(min_length=3, max_length=3)
    redaction_probes: RedactionProbeSet

    @field_validator("capabilities")
    @classmethod
    def require_sorted_unique_capabilities(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != tuple(sorted(set(value))):
            raise ValueError("serialized_capabilities_not_canonical")
        return value

    @field_validator("redaction_markers")
    @classmethod
    def require_all_redaction_markers(
        cls,
        value: tuple[RedactionMarker, ...],
    ) -> tuple[RedactionMarker, ...]:
        if value != ("artifact-body", "environment-values", "private-selection"):
            raise ValueError("serialized_redaction_markers_invalid")
        return value


class SerializedMetadataProviderConformance(_SerializedConformanceBase):
    module_kind: Literal["metadata-provider"]
    success: MetadataSuccessCase


class SerializedReleaseProviderConformance(_SerializedConformanceBase):
    module_kind: Literal["release-provider"]
    success: ReleaseSuccessCase


class SerializedDownloadClientConformance(_SerializedConformanceBase):
    module_kind: Literal["download-client"]
    success: DownloadSuccessCase


type SerializedConformanceFixture = Annotated[
    SerializedMetadataProviderConformance
    | SerializedReleaseProviderConformance
    | SerializedDownloadClientConformance,
    Field(discriminator="module_kind"),
]

SERIALIZED_CONFORMANCE_ADAPTER: TypeAdapter[SerializedConformanceFixture] = TypeAdapter(
    SerializedConformanceFixture
)


def parse_serialized_conformance_fixture(content: bytes) -> SerializedConformanceFixture:
    """Parse one versioned fixture without importing core or a concrete module."""

    return SERIALIZED_CONFORMANCE_ADAPTER.validate_json(content)


__all__ = [
    "SERIALIZED_CONFORMANCE_ADAPTER",
    "ArtifactDescriptor",
    "ConfigurationFreeCase",
    "DownloadSuccessCase",
    "MetadataEditorCase",
    "MetadataRetentionCase",
    "MetadataSuccessCase",
    "MissingConfigurationCase",
    "RedactionProbeSet",
    "ReleaseSuccessCase",
    "SerializedConformanceFixture",
    "SerializedDownloadClientConformance",
    "SerializedMetadataProviderConformance",
    "SerializedReleaseProviderConformance",
    "SerializedReleaseResult",
    "SerializedResolvedArtifact",
    "SerializedSafeReleaseSnapshot",
    "StableFailureCase",
    "is_safe_public_source_page",
    "is_safe_release_guid",
    "parse_serialized_conformance_fixture",
]
