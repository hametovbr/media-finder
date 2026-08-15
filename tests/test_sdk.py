import ast
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import BaseModel, Field, SecretStr, ValidationError

from media_finder import sdk
from media_finder.modules import registry as module_registry
from media_finder.modules.manual import ManualProvider
from media_finder.modules.tmdb import TmdbConfig, TmdbProvider
from media_finder.sdk import conformance
from media_finder.sdk.conformance import (
    ClientConformanceFixture,
    ProviderConformanceFixture,
    assert_client_conforms,
    assert_provider_conforms,
)
from media_finder.sdk.errors import ModuleError
from media_finder.sdk.protocols import MetadataProvider
from media_finder.sdk.settings import describe_settings
from media_finder.sdk.types import (
    CorrelationResult,
    DownloadDestination,
    ExportHeader,
    ExportWarning,
    MagnetArtifact,
    MediaKind,
    ModuleKind,
    ModuleManifest,
    PublicModel,
    RetentionActionKind,
    SubmissionResult,
    TorrentArtifact,
)


class Config(BaseModel):
    endpoint: str = Field(title="settings.endpoint", json_schema_extra={"order": 1})
    token: SecretStr = Field(title="settings.token", json_schema_extra={"secret": True, "order": 2})


def test_generic_settings_description_rejects_module_markup() -> None:
    fields = describe_settings(Config)
    assert [field.name for field in fields] == ["endpoint", "token"]
    assert fields[1].secret is True
    assert all(field.html is None and field.javascript is None for field in fields)


def test_environment_reference_is_exposed_by_the_public_module_sdk() -> None:
    reference_type = getattr(sdk, "EnvReference", None)
    assert reference_type is not None
    assert reference_type(value="env:THIRD_PARTY_TOKEN").variable_name == "THIRD_PARTY_TOKEN"


def test_module_manifest_rejects_markup_and_paths() -> None:
    manifest = ModuleManifest(
        key="safe", version="1.0.0", contract_version="1", name_key="module.safe"
    )
    assert manifest.key == "safe"


def test_fixture_modules_conform(fake_provider, fake_client) -> None:
    fixture = ProviderConformanceFixture(
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
    assert_provider_conforms(fake_provider, fixture)
    assert_client_conforms(
        fake_client,
        ClientConformanceFixture(
            destination="fixture",
            correlation="mf-acq-fixture",
            magnet=MagnetArtifact(uri="magnet:?xt=urn:btih:" + "a" * 40),
            torrent=TorrentArtifact(content=b"fixture"),
        ),
    )


class RealProviderTransport:
    def get_json(self, path: str, params: dict[str, str]) -> dict:
        if path == "/search/movie":
            return {"results": [{"id": 1, "title": "Fixture", "release_date": "2024-01-01"}]}
        if path == "/search/tv":
            return {"results": []}
        return {"id": 1, "title": "Fixture", "release_date": "2024-01-01"}


def test_real_metadata_providers_conform_without_application_dependencies() -> None:
    created = datetime(2026, 1, 1, tzinfo=UTC)
    assert_provider_conforms(
        ManualProvider(),
        ProviderConformanceFixture(
            query="Fixture",
            locale="en-US",
            kind=MediaKind.MOVIE,
            external_id="47e26ca2-f393-4a00-b33a-902d41d49714",
            raw_payload={
                "schema_version": "1",
                "kind": "movie",
                "locale": "en-US",
                "titles": {"en-US": "Fixture"},
            },
            expected_title="Fixture",
            created_at=created,
            retention_check_at=created,
            expected_retention_action=RetentionActionKind.NONE,
        ),
    )
    assert_provider_conforms(
        TmdbProvider(TmdbConfig(api_token="env:TMDB_TOKEN"), RealProviderTransport()),
        ProviderConformanceFixture(
            query="Fixture",
            locale="en-US",
            kind=MediaKind.MOVIE,
            external_id="1",
            raw_payload={"id": 1, "title": "Fixture", "release_date": "2024-01-01"},
            expected_title="Fixture",
            created_at=created,
            retention_check_at=created,
            expected_retention_action=RetentionActionKind.NONE,
            expected_error_code="metadata_identity_invalid",
        ),
    )


def test_public_models_never_contain_raw_provider_payload_fields() -> None:
    pending = list(PublicModel.__subclasses__())
    seen: set[type[PublicModel]] = set()
    while pending:
        model = pending.pop()
        if model in seen:
            continue
        seen.add(model)
        pending.extend(model.__subclasses__())
        forbidden = {
            name
            for name in model.model_fields
            if name in {"raw_payload", "provider_payload"} or name.startswith("raw_provider")
        }
        assert not forbidden, f"{model.__name__} exposes {sorted(forbidden)}"


def test_export_warning_headers_cannot_be_mutated_after_validation() -> None:
    warning = ExportWarning(headers=(ExportHeader(name="Warning", value="299 Media Finder safe"),))

    with pytest.raises(TypeError):
        warning.headers[0] = ExportHeader(name="Warning", value="changed")
    with pytest.raises(ValidationError):
        ExportHeader(name="Set-Cookie", value="session=unsafe")  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        ExportHeader(name="Warning", value="safe\r\nSet-Cookie: unsafe")
    assert warning.as_headers() == {"Warning": "299 Media Finder safe"}


def test_provider_protocol_and_first_party_modules_use_only_public_sdk() -> None:
    violations: list[str] = []
    if "execute_retention" in MetadataProvider.__dict__:
        violations.append("MetadataProvider.execute_retention")

    protocol_source = Path("src/media_finder/sdk/protocols.py").read_text(encoding="utf-8")
    for forbidden in ("InternalRetentionResult", "raw_payload"):
        if forbidden in protocol_source:
            violations.append(f"protocol exposes {forbidden}")

    private_boundary = Path("src/media_finder/sdk/_retention.py")
    if private_boundary.exists():
        violations.append(str(private_boundary))

    for module_path in (
        Path("src/media_finder/modules/manual/__init__.py"),
        Path("src/media_finder/modules/tmdb/__init__.py"),
        Path("src/media_finder/modules/qbittorrent/__init__.py"),
    ):
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported = node.module or ""
                if "sdk._" in imported or imported.endswith("config"):
                    violations.append(f"{module_path}:{imported}")

    assert not violations, f"private retention boundary leaks: {violations}"


def test_one_public_static_registry_composes_runtime_and_settings_without_switches() -> None:
    registry = getattr(module_registry, "FIRST_PARTY_MODULES", None)
    assert registry is not None
    assert set(registry.metadata_providers) == {"tmdb"}
    assert set(registry.download_clients) == {"qbittorrent"}
    assert registry.metadata_providers["tmdb"].retention_factory().manifest.key == "tmdb"
    assert registry.download_clients["qbittorrent"].config_model.__name__ == "QbittorrentConfig"
    with pytest.raises(TypeError):
        registry.metadata_providers["mutated"] = registry.metadata_providers["tmdb"]

    for path in (Path("src/media_finder/ui.py"), Path("src/media_finder/ui_runtime.py")):
        source = path.read_text(encoding="utf-8")
        assert "TmdbProvider" not in source
        assert "QbittorrentClient" not in source
        assert "QbittorrentConfig" not in source


class MagnetOnlyClient:
    manifest = ModuleManifest(
        key="third-party-magnet",
        version="1.0.0",
        contract_version="1",
        name_key="third.party.magnet",
        kind=ModuleKind.DOWNLOAD_CLIENT,
        capabilities=frozenset({"magnet", "live_destinations", "correlation"}),
    )
    config_model = EmptyConfig = type("EmptyConfig", (BaseModel,), {})

    def __init__(self) -> None:
        self.correlation: str | None = None

    def validate_config(self) -> None:
        return None

    def list_destinations(self) -> list[DownloadDestination]:
        return [DownloadDestination(key="third-party", label="Third party")]

    def submit(self, artifact, destination: str, correlation: str) -> SubmissionResult:
        assert isinstance(artifact, MagnetArtifact)
        if destination == "invalid":
            raise ModuleError(code="fixture_destination_invalid", message="Invalid destination")
        self.correlation = correlation
        return SubmissionResult(accepted=True, correlation=correlation)

    def find_by_correlation(self, correlation: str) -> CorrelationResult:
        return CorrelationResult(found=self.correlation == correlation, correlation=correlation)


def test_fixture_driven_conformance_is_capability_aware_and_third_party_safe(fake_provider) -> None:
    provider_fixture_type = getattr(conformance, "ProviderConformanceFixture", None)
    client_fixture_type = getattr(conformance, "ClientConformanceFixture", None)
    assert provider_fixture_type is not None
    assert client_fixture_type is not None

    fake_provider.manifest = fake_provider.manifest.model_copy(
        update={"capabilities": frozenset({"movie", "search", "fetch", "normalize"})}
    )
    provider_fixture = provider_fixture_type(
        query="Fixture query",
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
    assert_provider_conforms(fake_provider, provider_fixture)

    client = MagnetOnlyClient()
    client_fixture = client_fixture_type(
        destination="third-party",
        correlation="mf-acq-third-party",
        magnet=MagnetArtifact(uri="magnet:?xt=urn:btih:" + "a" * 40),
        error_destination="invalid",
        expected_error_code="fixture_destination_invalid",
    )
    assert_client_conforms(client, client_fixture)
    assert client.correlation == "mf-acq-third-party"


def test_provider_conformance_does_not_call_unadvertised_search(fake_provider) -> None:
    fake_provider.search = lambda _query, _locale: pytest.fail("unadvertised search was called")
    assert_provider_conforms(
        fake_provider,
        ProviderConformanceFixture(
            query="Fixture",
            locale="en-US",
            kind=MediaKind.MOVIE,
            external_id="1",
            raw_payload={"title": "Fixture"},
            expected_title="Fixture",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            retention_check_at=datetime(2026, 1, 1, tzinfo=UTC),
            expected_retention_action=RetentionActionKind.NONE,
        ),
    )
