"""Isolated TMDB metadata module contract."""

from __future__ import annotations

import ast
import email
import json
import os
import shutil
import subprocess
import sys
import zipfile
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast

import httpx
import pytest
from media_finder_metadata_tmdb import registration
from media_finder_metadata_tmdb.transport import TmdbEndpoint, TmdbTransport
from media_finder_sdk import (
    Artwork,
    EnvironmentVariableSpec,
    MediaKind,
    MetadataConformanceFixture,
    MetadataIdentity,
    MetadataSearchQuery,
    ModuleError,
    ModuleErrorData,
    ModuleKind,
    NormalizedMetadata,
    Provenance,
    ProviderPayload,
    Rating,
    RetentionAction,
    RetentionActionKind,
    RetentionPolicy,
    RetentionSubject,
    Season,
    SerializedMetadataProviderConformance,
    assert_metadata_registration_conforms,
    load_manifest,
    parse_serialized_conformance_fixture,
    resolve_module_environment,
)

ROOT = Path(__file__).parents[4]
PACKAGE_ROOT = ROOT / "packages" / "modules" / "metadata-tmdb"
UV = Path(
    shutil.which("uv") or ROOT / ".venv" / ("Scripts/uv.exe" if os.name == "nt" else "bin/uv")
)
UV_CACHE = ROOT / ".tools" / "uv-cache"
TOKEN = "tmdb-fixture-token-never-log"
FETCHED_AT = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


MOVIE_DETAILS: dict[str, object] = {
    "id": 129,
    "title": "Spirited Away",
    "original_title": "Sen to Chihiro no kamikakushi",
    "overview": "A journey through a spirit world.",
    "release_date": "2001-07-20",
    "runtime": 125,
    "vote_average": 8.5,
    "genres": [{"name": "Animation"}, {"name": "Fantasy"}],
    "production_countries": [{"name": "Japan"}],
    "production_companies": [{"name": "Studio Ghibli"}],
    "poster_path": "/spirited-poster.jpg",
    "backdrop_path": "/spirited-backdrop.jpg",
}
SERIES_DETAILS: dict[str, object] = {
    "id": 900,
    "name": "Fixture Series",
    "original_name": "Fixture Series Original",
    "overview": "A fixture series with a special.",
    "first_air_date": "2020-01-01",
    "vote_average": 7.25,
    "genres": [{"name": "Animation"}],
    "production_countries": [{"name": "United Kingdom"}],
    "production_companies": [{"name": "Fixture Studio"}],
    "poster_path": "/series-poster.jpg",
    "backdrop_path": "/series-backdrop.jpg",
    "seasons": [{"id": 9010, "season_number": 0, "name": "Specials"}],
}
SEASON_ZERO: dict[str, object] = {
    "id": 9010,
    "season_number": 0,
    "name": "Specials",
    "episodes": [
        {
            "id": 901,
            "episode_number": 1,
            "name": "The Special",
            "overview": "A special episode.",
            "air_date": "2020-02-01",
            "runtime": 24,
            "order": 1,
        }
    ],
}


def _response_payload(request: httpx.Request) -> dict[str, object]:
    payloads: dict[str, dict[str, object]] = {
        "/3/configuration": {"images": {"secure_base_url": "https://image.tmdb.org/t/p/"}},
        "/3/search/movie": {
            "results": [
                {
                    "id": 129,
                    "title": "Spirited Away",
                    "release_date": "2001-07-20",
                }
            ]
        },
        "/3/search/tv": {
            "results": [
                {
                    "id": 900,
                    "name": "Fixture Series",
                    "first_air_date": "2020-01-01",
                }
            ]
        },
        "/3/movie/129": MOVIE_DETAILS,
        "/3/tv/900": SERIES_DETAILS,
        "/3/tv/900/season/0": SEASON_ZERO,
    }
    return payloads[request.url.path]


class RecordingClientFactory:
    def __init__(
        self,
        handler: Callable[[httpx.Request], httpx.Response] | None = None,
    ) -> None:
        self.requests: list[httpx.Request] = []
        self.clients: list[httpx.Client] = []
        self._handler = handler or self._respond

    def __call__(self) -> httpx.Client:
        client = httpx.Client(transport=httpx.MockTransport(self._record))
        self.clients.append(client)
        return client

    def _record(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._handler(request)

    @staticmethod
    def _respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_response_payload(request))


def _movie_identity() -> MetadataIdentity:
    return MetadataIdentity(
        provider_id="tmdb",
        external_id="129",
        media_kind=MediaKind.MOVIE,
        locale="en-US",
    )


def _movie_metadata() -> NormalizedMetadata:
    return NormalizedMetadata(
        kind=MediaKind.MOVIE,
        titles={"en-US": "Spirited Away"},
        original_title="Sen to Chihiro no kamikakushi",
        year=2001,
        plot="A journey through a spirit world.",
        release_date=date(2001, 7, 20),
        runtime_minutes=125,
        provider_ids={"tmdb": "129"},
        ratings=(Rating(source="tmdb", value=8.5),),
        genres=("Animation", "Fantasy"),
        countries=("Japan",),
        studios=("Studio Ghibli",),
        artwork=(
            Artwork(
                kind="poster",
                url="https://image.tmdb.org/t/p/original/spirited-poster.jpg",
                language="en-US",
            ),
            Artwork(
                kind="backdrop",
                url="https://image.tmdb.org/t/p/original/spirited-backdrop.jpg",
                language="en-US",
            ),
        ),
        provenance=Provenance(
            provider_id="tmdb",
            external_id="129",
            locale="en-US",
            fetched_at=FETCHED_AT,
            source_label="TMDB",
        ),
        completeness=1.0,
        structural_quality=1.0,
    )


def _module(factory: RecordingClientFactory | None = None):
    return registration(
        client_factory=factory or RecordingClientFactory(),
        clock=lambda: FETCHED_AT,
    )


def test_tmdb_wheel_is_independent_versioned_and_contains_declared_resources(
    tmp_path: Path,
) -> None:
    environment = {**os.environ, "UV_CACHE_DIR": str(UV_CACHE)}
    destination = tmp_path / "wheels"
    completed = subprocess.run(
        [
            str(UV),
            "build",
            "--wheel",
            "--package",
            "media-finder-metadata-tmdb",
            "--out-dir",
            str(destination),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    wheel = next(destination.glob("*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        names = frozenset(archive.namelist())
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = email.message_from_bytes(archive.read(metadata_name))

    package = "media_finder_metadata_tmdb"
    assert {
        f"{package}/__init__.py",
        f"{package}/module.toml",
        f"{package}/py.typed",
        f"{package}/translations/en.json",
        f"{package}/translations/ru.json",
        f"{package}/fixtures/conformance.json",
        f"{package}/fixtures/movie.json",
        f"{package}/fixtures/series.json",
        f"{package}/fixtures/season-0.json",
    } <= names
    requirements = tuple(metadata.get_all("Requires-Dist", []))
    assert any(value.lower().startswith("media-finder-module-sdk") for value in requirements)
    assert any(value.lower().startswith("httpx") for value in requirements)
    assert any(value.lower().startswith("python-dateutil") for value in requirements)
    assert not any("media-finder-core" in value.lower() for value in requirements)
    assert not any("media-finder-control-contracts" in value.lower() for value in requirements)
    manifest = load_manifest(PACKAGE_ROOT / f"src/{package}/module.toml")
    assert metadata["Version"] == manifest.module_version

    target = tmp_path / "installed"
    subprocess.run(
        [str(UV), "pip", "install", "--target", str(target), "--no-deps", str(wheel)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    probe = "\n".join(
        (
            "import pathlib, sys",
            f"target = pathlib.Path({str(target)!r}).resolve()",
            "sys.path.insert(0, str(target))",
            "import media_finder_metadata_tmdb as module",
            "assert pathlib.Path(module.__file__).resolve().is_relative_to(target)",
            "assert module.__all__ == ['registration']",
        )
    )
    subprocess.run(
        [sys.executable, "-I", "-c", probe],
        cwd=target,
        check=True,
        capture_output=True,
        text=True,
    )


def test_tmdb_manifest_declares_exact_secret_environment_and_public_sdk_only() -> None:
    package = PACKAGE_ROOT / "src/media_finder_metadata_tmdb"
    manifest = load_manifest(package / "module.toml")

    assert manifest.module_id == "tmdb"
    assert manifest.module_kind is ModuleKind.METADATA_PROVIDER
    assert manifest.capabilities == {
        "search",
        "fetch",
        "normalize",
        "retention",
        "export-warning",
    }
    assert manifest.environment == (
        EnvironmentVariableSpec(
            name="TMDB_TOKEN",
            required=True,
            secret=True,
            description_key="module.tmdb.environment.token",
        ),
    )
    assert manifest.attribution is not None
    assert manifest.attribution.notice_key == "module.tmdb.notice"
    assert str(manifest.attribution.url) == "https://www.themoviedb.org/"
    assert _module().editor is None

    forbidden = (
        "media_finder_core",
        "media_finder_control",
        "media_finder_metadata_manual",
        "sqlalchemy",
        "fastapi",
        "jinja2",
    )
    violations: list[str] = []
    for path in sorted(package.rglob("*.py")):
        tree = ast.parse(path.read_text("utf-8"), filename=str(path))
        for node in ast.walk(tree):
            imported: tuple[str, ...] = ()
            if isinstance(node, ast.Import):
                imported = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported = (node.module,)
            for name in imported:
                if name.startswith(forbidden):
                    violations.append(f"{path.name}:{node.lineno}:{name}")
    assert violations == []


def test_tmdb_movie_registration_passes_public_conformance_and_closes_resources() -> None:
    fixture_bytes = (
        PACKAGE_ROOT / "src/media_finder_metadata_tmdb/fixtures/conformance.json"
    ).read_bytes()
    serialized = parse_serialized_conformance_fixture(fixture_bytes)
    assert isinstance(serialized, SerializedMetadataProviderConformance)
    assert TOKEN.encode() not in fixture_bytes
    clients = RecordingClientFactory()
    module = _module(clients)
    success = serialized.success
    failures = {failure.operation: failure.error for failure in serialized.stable_failures}
    missing = serialized.missing_configuration
    assert missing.applicable is True
    with pytest.raises(ModuleError) as missing_error:
        resolve_module_environment(module.manifest, {})
    assert missing_error.value.category == missing.error.category
    assert missing_error.value.code == missing.error.code
    assert dict(missing_error.value.safe_details) == dict(missing.error.safe_details)

    assert_metadata_registration_conforms(
        module,
        MetadataConformanceFixture(
            environment={"TMDB_TOKEN": TOKEN, "UNDECLARED_SECRET": "must-not-be-visible"},
            query=success.query,
            expected_results=success.results,
            identity=success.identity,
            expected_payload=ProviderPayload(data=MOVIE_DETAILS),
            expected_metadata=success.normalized,
            invalid_identity=success.identity.model_copy(
                update={"external_id": "../configuration"}
            ),
            expected_error_code=failures["fetch-invalid-identity"].code,
            created_at=success.retention.created_at,
            now=success.retention.now,
            expected_policy=success.retention.policy,
            expected_action=success.retention.action,
            expected_warning=success.retention.warning,
        ),
    )

    assert clients.clients
    assert all(client.is_closed for client in clients.clients)
    assert all(request.url.host == "api.themoviedb.org" for request in clients.requests)
    assert all(request.url.scheme == "https" for request in clients.requests)
    assert all(
        request.headers["authorization"] == f"Bearer {TOKEN}" for request in clients.requests
    )
    rendered_requests = repr(clients.requests)
    assert "UNDECLARED_SECRET" not in rendered_requests
    assert "must-not-be-visible" not in rendered_requests

    invalid_provider = module.build(
        resolve_module_environment(module.manifest, {"TMDB_TOKEN": TOKEN})
    )
    try:
        with pytest.raises(ModuleError) as invalid_identity:
            invalid_provider.fetch(
                success.identity.model_copy(update={"external_id": "../configuration"})
            )
    finally:
        invalid_provider.close()
    assert ModuleErrorData.from_error(invalid_identity.value) == failures["fetch-invalid-identity"]


def test_tmdb_series_fetch_normalizes_season_zero_specials() -> None:
    clients = RecordingClientFactory()
    module = _module(clients)
    environment = resolve_module_environment(module.manifest, {"TMDB_TOKEN": TOKEN})
    provider = module.build(environment)
    identity = MetadataIdentity(
        provider_id="tmdb",
        external_id="900",
        media_kind=MediaKind.SERIES,
        locale="en-US",
    )

    try:
        provider.validate()
        raw = provider.fetch(identity)
        normalized = provider.normalize(raw, identity)
    finally:
        provider.close()
        provider.close()

    assert raw.data["id"] == 900
    assert normalized.kind is MediaKind.SERIES
    assert normalized.titles == {"en-US": "Fixture Series"}
    assert normalized.provider_ids == {"tmdb": "900"}
    assert normalized.provenance == Provenance(
        provider_id="tmdb",
        external_id="900",
        locale="en-US",
        fetched_at=FETCHED_AT,
        source_label="TMDB",
    )
    assert normalized.seasons == (
        Season(
            number=0,
            title="Specials",
            provider_ids={"tmdb": "9010"},
            episodes=(
                # Keep Season 00 explicit; specials are never folded into season one.
                normalized.seasons[0].episodes[0].model_copy(),
            ),
        ),
    )
    special = normalized.seasons[0].episodes[0]
    assert special.number == 1
    assert special.title == "The Special"
    assert special.plot == "A special episode."
    assert special.air_date == date(2020, 2, 1)
    assert special.runtime_minutes == 24
    assert special.provider_ids == {"tmdb": "901"}
    assert special.ordering == 1
    assert [request.url.path for request in clients.requests] == [
        "/3/configuration",
        "/3/tv/900",
        "/3/tv/900/season/0",
    ]
    assert all(client.is_closed for client in clients.clients)


def test_tmdb_series_fetch_bounds_and_deduplicates_season_requests() -> None:
    identity = MetadataIdentity(
        provider_id="tmdb",
        external_id="900",
        media_kind=MediaKind.SERIES,
        locale="en-US",
    )

    over_limit = {
        **SERIES_DETAILS,
        "seasons": [{"season_number": number} for number in range(101)],
    }

    def oversized_response(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/3/tv/900"
        return httpx.Response(200, json=over_limit)

    oversized_clients = RecordingClientFactory(oversized_response)
    oversized_provider = _module(oversized_clients).build(
        resolve_module_environment(_module().manifest, {"TMDB_TOKEN": TOKEN})
    )
    try:
        with pytest.raises(ModuleError) as captured:
            oversized_provider.fetch(identity)
    finally:
        oversized_provider.close()

    assert captured.value.code == "metadata_provider_unavailable"
    assert [request.url.path for request in oversized_clients.requests] == ["/3/tv/900"]

    duplicate_summaries = {
        **SERIES_DETAILS,
        "seasons": [{"season_number": 0}, {"season_number": 0}],
    }

    def duplicate_response(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/3/tv/900":
            return httpx.Response(200, json=duplicate_summaries)
        assert request.url.path == "/3/tv/900/season/0"
        return httpx.Response(200, json=SEASON_ZERO)

    duplicate_clients = RecordingClientFactory(duplicate_response)
    duplicate_provider = _module(duplicate_clients).build(
        resolve_module_environment(_module().manifest, {"TMDB_TOKEN": TOKEN})
    )
    try:
        duplicate_provider.fetch(identity)
    finally:
        duplicate_provider.close()

    assert [request.url.path for request in duplicate_clients.requests] == [
        "/3/tv/900",
        "/3/tv/900/season/0",
    ]


def test_tmdb_typed_endpoints_reject_untrusted_paths_before_http_or_secret_use() -> None:
    module = _module()
    environment = resolve_module_environment(module.manifest, {"TMDB_TOKEN": TOKEN})
    requests: list[httpx.Request] = []
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: requests.append(request) or httpx.Response(200, json={})
        )
    )
    transport = TmdbTransport(environment=environment, client=client)

    with pytest.raises(ValueError, match="tmdb_endpoint_invalid"):
        transport.get_json(cast(TmdbEndpoint, "https://attacker.example.test/steal"), {})
    with pytest.raises(ValueError, match="metadata_identity_invalid"):
        TmdbEndpoint.movie("../../configuration")
    with pytest.raises(ValueError, match="metadata_identity_invalid"):
        TmdbEndpoint.season("900", -1)

    assert requests == []
    assert TOKEN not in repr(transport)
    transport.close()
    transport.close()
    assert client.is_closed


def test_tmdb_failures_are_standardized_and_redact_secrets_and_sensitive_urls(
    caplog: pytest.LogCaptureFixture,
) -> None:
    serialized = parse_serialized_conformance_fixture(
        (PACKAGE_ROOT / "src/media_finder_metadata_tmdb/fixtures/conformance.json").read_bytes()
    )
    assert isinstance(serialized, SerializedMetadataProviderConformance)
    failures = {failure.operation: failure.error for failure in serialized.stable_failures}
    probes = serialized.redaction_probes

    def fail(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"Bearer {probes.environment_value}"
        raise RuntimeError(
            f"failed https://api.example.test/passkey/{probes.credential}/file"
            f"?api_key={probes.environment_value}#fragment "
            f"{probes.artifact_body} {probes.private_selection}"
        )

    caplog.set_level("DEBUG")
    clients = RecordingClientFactory(fail)
    module = _module(clients)
    environment = resolve_module_environment(
        module.manifest,
        {"TMDB_TOKEN": probes.environment_value},
    )
    provider = module.build(environment)

    try:
        with pytest.raises(ModuleError) as captured:
            provider.search(MetadataSearchQuery(query="Fixture", locale="en-US"))
    finally:
        provider.close()
        provider.close()

    error = captured.value
    assert ModuleErrorData.from_error(error) == failures["search-unavailable"]
    rendered = f"{error!s} {error!r} {error.safe_details!r}"
    assert error.code == "metadata_provider_unavailable"
    assert TOKEN not in rendered
    assert "passkey" not in rendered
    assert "api_key" not in rendered
    assert "fragment" not in rendered
    assert "https://" not in rendered
    safe_public = f"{rendered} {caplog.text}"
    for probe in probes.model_dump().values():
        assert probe not in safe_public
    assert all(client.is_closed for client in clients.clients)


def test_tmdb_malformed_search_results_raise_a_standardized_safe_failure() -> None:
    def malformed(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/3/configuration":
            return httpx.Response(200, json={})
        return httpx.Response(
            200,
            json={"results": [{"id": 129, "title": "Broken date", "release_date": "not-a-date"}]},
        )

    module = _module(RecordingClientFactory(malformed))
    provider = module.build(resolve_module_environment(module.manifest, {"TMDB_TOKEN": TOKEN}))

    try:
        with pytest.raises(ModuleError) as captured:
            provider.search(MetadataSearchQuery(query="Broken", locale="en-US"))
    finally:
        provider.close()

    assert captured.value.code == "metadata_provider_unavailable"
    assert str(captured.value) == "metadata_provider_unavailable"


def test_tmdb_rejects_an_oversized_json_response_before_provider_validation() -> None:
    oversized = json.dumps({"overview": "x" * (2 * 1024 * 1024 + 1)}).encode()

    def respond(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=oversized,
            headers={"content-type": "application/json"},
        )

    module = _module(RecordingClientFactory(respond))
    provider = module.build(resolve_module_environment(module.manifest, {"TMDB_TOKEN": TOKEN}))
    try:
        with pytest.raises(ModuleError) as captured:
            provider.fetch(_movie_identity())
    finally:
        provider.close()

    assert captured.value.code == "metadata_provider_unavailable"


def test_tmdb_retention_is_configuration_free_and_uses_calendar_month_boundaries() -> None:
    clients = RecordingClientFactory()
    retention = _module(clients).retention()
    created = datetime(2024, 8, 31, 12, tzinfo=UTC)
    policy = retention.retention_for(created)
    subject = RetentionSubject(identity=_movie_identity(), policy=policy)

    assert clients.clients == []
    assert policy == RetentionPolicy(
        refresh_after=datetime(2025, 1, 31, 12, tzinfo=UTC),
        expires_at=datetime(2025, 2, 28, 12, tzinfo=UTC),
    )
    assert retention.plan(subject, datetime(2025, 1, 31, 11, 59, 59, tzinfo=UTC)) == (
        RetentionAction(kind=RetentionActionKind.NONE)
    )
    assert retention.plan(subject, datetime(2025, 1, 31, 12, tzinfo=UTC)) == RetentionAction(
        kind=RetentionActionKind.REFRESH
    )
    assert retention.plan(subject, datetime(2025, 2, 28, 12, tzinfo=UTC)) == RetentionAction(
        kind=RetentionActionKind.PURGE,
        mandatory=True,
    )
    warning = retention.export_warning(policy, datetime(2025, 1, 1, tzinfo=UTC))
    assert warning is not None
    assert {header.name: header.value for header in warning.headers} == {
        "Warning": '299 Media Finder "Provider-derived metadata has a retention deadline"',
        "Sunset": "Fri, 28 Feb 2025 12:00:00 GMT",
        "X-Media-Finder-Metadata-Expires": "2025-02-28T12:00:00+00:00",
    }

    retention.close()
    retention.close()
