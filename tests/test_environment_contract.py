from dataclasses import replace
from datetime import UTC, datetime

import httpx
import pytest
from pydantic import ValidationError

from media_finder import sdk
from media_finder.modules.registry import FIRST_PARTY_MODULES
from media_finder.sdk.conformance import ClientConformanceFixture, ProviderConformanceFixture
from media_finder.sdk.registration import (
    DownloadClientRegistration,
    MetadataProviderRegistration,
    StaticModuleRegistry,
)
from media_finder.sdk.types import (
    MagnetArtifact,
    MediaKind,
    RetentionActionKind,
    TorrentArtifact,
)


def _environment_type():
    contract = getattr(sdk, "EnvironmentVariableSpec", None)
    assert contract is not None, "public environment declaration is missing"
    return contract


def test_first_party_modules_publish_exact_environment_contracts() -> None:
    environment_type = _environment_type()

    manual = FIRST_PARTY_MODULES.metadata_providers["manual"].environment
    tmdb = FIRST_PARTY_MODULES.metadata_providers["tmdb"].environment
    qbittorrent = FIRST_PARTY_MODULES.download_clients["qbittorrent"].environment

    assert manual == ()
    assert tmdb == (
        environment_type(
            name="TMDB_TOKEN",
            required=True,
            secret=True,
            description_key="module.tmdb.environment.token",
        ),
    )
    assert [item.name for item in qbittorrent] == [
        "QBITTORRENT_URL",
        "QBITTORRENT_USERNAME",
        "QBITTORRENT_PASSWORD",
    ]
    assert [item.secret for item in qbittorrent] == [False, True, True]


def test_environment_contract_rejects_invalid_names_and_duplicates() -> None:
    environment_type = _environment_type()
    with pytest.raises(ValidationError):
        environment_type(
            name="dynamic-prefix_*",
            required=True,
            secret=False,
            description_key="module.fixture.environment.value",
        )
    with pytest.raises(ValidationError):
        environment_type(
            name="FIXTURE_VALUE",
            required=True,
            secret=False,
            description_key="",
        )
    with pytest.raises(ValidationError):
        environment_type(
            name="FIXTURE_VALUE",
            required=True,
            secret=False,
            description_key="   ",
        )

    duplicate = environment_type(
        name="TMDB_TOKEN",
        required=True,
        secret=False,
        description_key="module.conflict.environment.token",
    )
    conflicting_client = replace(
        FIRST_PARTY_MODULES.download_clients["qbittorrent"], environment=(duplicate,)
    )
    with pytest.raises(ValueError, match="environment_variable_conflict"):
        StaticModuleRegistry(
            metadata_providers=FIRST_PARTY_MODULES.metadata_providers,
            download_clients={"qbittorrent": conflicting_client},
        )


def test_environment_resolution_reports_only_missing_names() -> None:
    environment_type = _environment_type()
    resolver = getattr(sdk, "resolve_environment", None)
    error_type = getattr(sdk, "EnvironmentConfigurationError", None)
    assert resolver is not None
    assert error_type is not None
    contract = (
        environment_type(
            name="FIXTURE_URL",
            required=True,
            secret=False,
            description_key="fixture.url",
        ),
        environment_type(
            name="FIXTURE_TOKEN",
            required=True,
            secret=True,
            description_key="fixture.token",
        ),
    )

    with pytest.raises(error_type) as rejected:
        resolver(contract, {"FIXTURE_TOKEN": "must-never-escape"})

    assert rejected.value.code == "integration_environment_missing"
    assert rejected.value.missing == ("FIXTURE_URL",)
    assert "must-never-escape" not in str(rejected.value)


def test_prowlarr_publishes_the_same_public_descriptor_type() -> None:
    descriptor = getattr(sdk, "IntegrationDescriptor", None)
    assert descriptor is not None
    from media_finder.integration_runtime import PROWLARR_INTEGRATION

    assert isinstance(PROWLARR_INTEGRATION, descriptor)
    assert [item.name for item in PROWLARR_INTEGRATION.environment] == [
        "PROWLARR_URL",
        "PROWLARR_API_KEY",
    ]
    assert [item.secret for item in PROWLARR_INTEGRATION.environment] == [False, True]


def test_shared_conformance_exercises_declared_and_missing_environment() -> None:
    from media_finder.sdk import conformance

    assertion = getattr(conformance, "assert_environment_conforms", None)
    assert assertion is not None, "shared environment conformance is missing"
    assertion(
        FIRST_PARTY_MODULES.metadata_providers["manual"].environment,
        {},
    )
    assertion(
        FIRST_PARTY_MODULES.metadata_providers["tmdb"].environment,
        {"TMDB_TOKEN": "fixture-secret"},
    )
    assertion(
        FIRST_PARTY_MODULES.download_clients["qbittorrent"].environment,
        {
            "QBITTORRENT_URL": "https://qb.example.test",
            "QBITTORRENT_USERNAME": "fixture-user",
            "QBITTORRENT_PASSWORD": "fixture-secret",
        },
    )


def test_registration_conformance_requires_exact_classification_and_builds_module(
    fake_provider, fake_client
) -> None:
    from media_finder.sdk import conformance

    provider_assertion = getattr(conformance, "assert_provider_registration_conforms", None)
    client_assertion = getattr(conformance, "assert_client_registration_conforms", None)
    assert provider_assertion is not None, "provider registration conformance is missing"
    assert client_assertion is not None, "client registration conformance is missing"
    environment_type = _environment_type()
    expected = (
        environment_type(
            name="FIXTURE_URL",
            required=True,
            secret=False,
            description_key="fixture.url",
        ),
        environment_type(
            name="FIXTURE_TOKEN",
            required=True,
            secret=True,
            description_key="fixture.token",
        ),
    )
    values = {"FIXTURE_URL": "https://fixture.invalid", "FIXTURE_TOKEN": "fixture-secret"}
    builds: list[dict[str, object]] = []

    def build_provider(payload, http_client_factory, secret_resolver):
        del http_client_factory
        builds.append(dict(payload))
        assert secret_resolver("env:FIXTURE_TOKEN") == "fixture-secret"
        return fake_provider

    def build_client(payload, http_client_factory, secret_resolver):
        del http_client_factory
        builds.append(dict(payload))
        assert secret_resolver("env:FIXTURE_TOKEN") == "fixture-secret"
        return fake_client

    provider = MetadataProviderRegistration(
        key="fixture-provider",
        config_model=fake_provider.config_model,
        retention_factory=lambda: fake_provider,
        build=build_provider,
        environment=expected,
    )
    client = DownloadClientRegistration(
        key="fixture-client",
        config_model=fake_client.config_model,
        build=build_client,
        environment=expected,
    )
    provider_fixture = ProviderConformanceFixture(
        query="Fixture",
        locale="en-US",
        kind=MediaKind.MOVIE,
        external_id="1",
        raw_payload={"title": "Fixture"},
        expected_title="Fixture",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        retention_check_at=datetime(2026, 1, 1, tzinfo=UTC),
        expected_retention_action=RetentionActionKind.NONE,
        expected_error_code="fixture_identity_invalid",
    )
    client_fixture = ClientConformanceFixture(
        destination="fixture",
        correlation="mf-acq-fixture",
        magnet=MagnetArtifact(uri="magnet:?xt=urn:btih:" + "a" * 40),
        torrent=TorrentArtifact(content=b"fixture"),
    )

    def unused_http() -> httpx.Client:
        return httpx.Client(
            transport=httpx.MockTransport(lambda _: pytest.fail("HTTP must not be requested"))
        )

    built_provider = provider_assertion(provider, expected, values, unused_http)
    built_client = client_assertion(client, expected, values, unused_http)
    conformance.assert_provider_conforms(built_provider, provider_fixture)
    conformance.assert_client_conforms(built_client, client_fixture)

    assert builds == [values, values]
    misclassified = (expected[0], expected[1].model_copy(update={"secret": False}))
    with pytest.raises(AssertionError, match="environment declaration mismatch"):
        provider_assertion(provider, misclassified, values, unused_http)


def test_first_party_registration_conformance_builds_from_exact_environment() -> None:
    from media_finder.sdk import conformance

    created: list[httpx.Client] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.themoviedb.org":
            return httpx.Response(200, json={})
        if request.url.path.endswith("/api/v2/auth/login"):
            return httpx.Response(200, text="Ok.")
        return httpx.Response(200, json={})

    def clients() -> httpx.Client:
        client = httpx.Client(transport=httpx.MockTransport(handler))
        created.append(client)
        return client

    manual = FIRST_PARTY_MODULES.metadata_providers["manual"]
    tmdb = FIRST_PARTY_MODULES.metadata_providers["tmdb"]
    qbittorrent = FIRST_PARTY_MODULES.download_clients["qbittorrent"]

    built_manual = conformance.assert_provider_registration_conforms(manual, (), {}, clients)
    built_tmdb = conformance.assert_provider_registration_conforms(
        tmdb,
        (
            _environment_type()(
                name="TMDB_TOKEN",
                required=True,
                secret=True,
                description_key="module.tmdb.environment.token",
            ),
        ),
        {"TMDB_TOKEN": "fixture-token"},
        clients,
    )
    built_qbittorrent = conformance.assert_client_registration_conforms(
        qbittorrent,
        qbittorrent.environment,
        {
            "QBITTORRENT_URL": "https://qb.example.test",
            "QBITTORRENT_USERNAME": "fixture-user",
            "QBITTORRENT_PASSWORD": "fixture-password",
        },
        clients,
    )

    assert [built_manual.manifest.key, built_tmdb.manifest.key] == ["manual", "tmdb"]
    assert built_qbittorrent.manifest.key == "qbittorrent"
    for client in created:
        client.close()
