"""Small public conformance assertions usable by third-party module fixtures."""

import inspect
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .errors import ModuleError
from .protocols import DownloadClient, MetadataProvider
from .registration import (
    DownloadClientRegistration,
    EnvironmentConfigurationError,
    HttpClientFactory,
    MetadataProviderRegistration,
    SecretResolver,
    resolve_environment,
)
from .types import (
    EnvironmentVariableSpec,
    ExportWarning,
    MagnetArtifact,
    MediaKind,
    RetentionActionKind,
    TorrentArtifact,
)

FORBIDDEN_ARGUMENTS = {
    "database",
    "db",
    "session",
    "repository",
    "catalog",
    "jinja",
    "environment",
    "template",
    "template_path",
    "html",
    "javascript",
    "artifact_path",
    "writable_path",
}
ESSENTIAL_PROVIDER_CAPABILITIES = frozenset({"search", "fetch", "normalize"})


def assert_environment_conforms(
    declarations: tuple[EnvironmentVariableSpec, ...],
    values: Mapping[str, str],
) -> None:
    """Exercise success and every required missing-variable boundary."""

    assert resolve_environment(declarations, values) == dict(values)
    for declaration in declarations:
        if not declaration.required:
            continue
        missing_values = dict(values)
        missing_values.pop(declaration.name, None)
        try:
            resolve_environment(declarations, missing_values)
        except EnvironmentConfigurationError as error:
            assert declaration.name in error.missing
            for other in values.values():
                assert other not in str(error)
        else:
            raise AssertionError(f"missing variable was accepted: {declaration.name}")


@dataclass(frozen=True, slots=True)
class ProviderConformanceFixture:
    query: str
    locale: str
    kind: MediaKind
    external_id: str
    raw_payload: dict[str, Any]
    expected_title: str
    created_at: datetime
    retention_check_at: datetime
    expected_retention_action: RetentionActionKind
    expected_error_code: str


@dataclass(frozen=True, slots=True)
class ClientConformanceFixture:
    destination: str
    correlation: str
    magnet: MagnetArtifact | None = None
    torrent: TorrentArtifact | None = None
    error_destination: str | None = None
    expected_error_code: str | None = None


def assert_provider_registration_conforms(
    registration: MetadataProviderRegistration,
    expected_environment: tuple[EnvironmentVariableSpec, ...],
    values: Mapping[str, str],
    http_client_factory: HttpClientFactory,
) -> MetadataProvider:
    """Exercise exact declarations and successful production construction."""

    assert registration.environment == expected_environment, "environment declaration mismatch"
    assert_environment_conforms(registration.environment, values)
    provider = registration.build(
        resolve_environment(registration.environment, values),
        http_client_factory,
        _fixture_secret_resolver(registration.environment, values),
    )
    assert isinstance(provider, MetadataProvider)
    assert provider.manifest.key == registration.key
    provider.validate_config()
    return provider


def assert_client_registration_conforms(
    registration: DownloadClientRegistration,
    expected_environment: tuple[EnvironmentVariableSpec, ...],
    values: Mapping[str, str],
    http_client_factory: HttpClientFactory,
) -> DownloadClient:
    """Exercise exact declarations and successful production construction."""

    assert registration.environment == expected_environment, "environment declaration mismatch"
    assert_environment_conforms(registration.environment, values)
    client = registration.build(
        resolve_environment(registration.environment, values),
        http_client_factory,
        _fixture_secret_resolver(registration.environment, values),
    )
    assert isinstance(client, DownloadClient)
    assert client.manifest.key == registration.key
    client.validate_config()
    return client


def _fixture_secret_resolver(
    declarations: tuple[EnvironmentVariableSpec, ...], values: Mapping[str, str]
) -> SecretResolver:
    declared = {declaration.name for declaration in declarations}

    def resolve(reference: str) -> str:
        if not reference.startswith("env:") or reference[4:] not in declared:
            raise AssertionError("builder requested an undeclared environment variable")
        return values[reference[4:]]

    return resolve


def _assert_boundary(module: object) -> None:
    constructor_parameters = set(inspect.signature(type(module)).parameters)
    forbidden_constructor = constructor_parameters & FORBIDDEN_ARGUMENTS
    assert not forbidden_constructor, (
        f"constructor exposes forbidden dependencies: {sorted(forbidden_constructor)}"
    )
    for name, value in vars(module).items():
        type_path = f"{type(value).__module__}.{type(value).__qualname__}".lower()
        assert name not in FORBIDDEN_ARGUMENTS, f"instance stores forbidden dependency: {name}"
        assert not any(
            marker in type_path
            for marker in ("sqlalchemy", "jinja", "media_finder.domain", "media_finder.models")
        ), f"instance stores forbidden application type: {type_path}"
    for name, method in inspect.getmembers(module, predicate=callable):
        if name.startswith("_"):
            continue
        parameters = set(inspect.signature(method).parameters)
        forbidden = parameters & FORBIDDEN_ARGUMENTS
        assert not forbidden, f"{name} exposes forbidden dependencies: {sorted(forbidden)}"


def assert_provider_conforms(
    provider: MetadataProvider, fixture: ProviderConformanceFixture
) -> None:
    assert isinstance(provider, MetadataProvider)
    _assert_boundary(provider)
    provider.validate_config()
    assert provider.manifest.contract_version == "1"
    assert provider.attribution().provider_key == provider.manifest.key
    missing = ESSENTIAL_PROVIDER_CAPABILITIES - provider.manifest.capabilities
    assert not missing, f"essential provider capabilities missing: {sorted(missing)}"
    search_results = provider.search(fixture.query, fixture.locale)
    assert any(
        result.external_id == fixture.external_id
        and result.kind is fixture.kind
        and result.locale == fixture.locale
        for result in search_results
    )
    payload = provider.fetch(fixture.kind.value, fixture.external_id, fixture.locale)
    assert payload == fixture.raw_payload
    normalized = provider.normalize(
        payload, fixture.kind.value, fixture.external_id, fixture.locale
    )
    assert normalized.kind is fixture.kind
    assert normalized.provenance.provider_key == provider.manifest.key
    assert normalized.provenance.external_id == fixture.external_id
    assert normalized.provenance.locale == fixture.locale
    assert fixture.expected_title in normalized.titles.values()
    policy = provider.retention_for(fixture.created_at)
    action = provider.plan_retention(policy, fixture.retention_check_at)
    assert action.kind is fixture.expected_retention_action
    warning = provider.export_warning(policy, fixture.retention_check_at)
    assert warning is None or isinstance(warning, ExportWarning)
    try:
        provider.fetch(fixture.kind.value, "invalid", fixture.locale)
    except ModuleError as error:
        assert error.code == fixture.expected_error_code
    else:
        raise AssertionError("provider fixture expected a standardized error")


def assert_client_conforms(client: DownloadClient, fixture: ClientConformanceFixture) -> None:
    assert isinstance(client, DownloadClient)
    _assert_boundary(client)
    client.validate_config()
    destinations = client.list_destinations()
    assert destinations
    assert fixture.destination in {destination.key for destination in destinations}
    artifacts: list[MagnetArtifact | TorrentArtifact] = []
    if "magnet" in client.manifest.capabilities:
        assert fixture.magnet is not None
        artifacts.append(fixture.magnet)
    if "torrent" in client.manifest.capabilities:
        assert fixture.torrent is not None
        artifacts.append(fixture.torrent)
    assert artifacts
    for artifact in artifacts:
        result = client.submit(artifact, fixture.destination, fixture.correlation)
        assert result.correlation == fixture.correlation
        assert client.find_by_correlation(fixture.correlation).correlation == fixture.correlation
    if fixture.expected_error_code is not None:
        assert fixture.error_destination is not None
        try:
            client.submit(artifacts[0], fixture.error_destination, fixture.correlation)
        except ModuleError as error:
            assert error.code == fixture.expected_error_code
        else:
            raise AssertionError("client fixture expected a standardized error")
