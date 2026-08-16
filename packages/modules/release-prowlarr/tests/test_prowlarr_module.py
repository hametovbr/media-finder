"""Isolated Prowlarr release-provider module contract."""

from __future__ import annotations

import ast
import email
import hashlib
import logging
import os
import shutil
import subprocess
import sys
import zipfile
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from media_finder_release_prowlarr import registration
from media_finder_release_prowlarr.transport import ProwlarrLimits
from media_finder_sdk import (
    ArtifactDescriptor,
    EnvironmentVariableSpec,
    MagnetArtifact,
    ModuleError,
    ModuleErrorData,
    ModuleKind,
    PrivateReleaseSelection,
    ReleaseCandidate,
    ReleaseConformanceFixture,
    ReleaseSearchQuery,
    SerializedReleaseProviderConformance,
    TorrentArtifact,
    assert_release_registration_conforms,
    load_manifest,
    parse_serialized_conformance_fixture,
    resolve_module_environment,
)

ROOT = Path(__file__).parents[4]
PACKAGE_ROOT = ROOT / "packages" / "modules" / "release-prowlarr"
UV = Path(
    shutil.which("uv") or ROOT / ".venv" / ("Scripts/uv.exe" if os.name == "nt" else "bin/uv")
)
UV_CACHE = ROOT / ".tools" / "uv-cache"
BASE_URL = "https://prowlarr.example.test/reverse/prowlarr"
API_KEY = "prowlarr-fixture-api-key-never-log"
DOWNLOAD_SECRET = "download-passkey-never-log"
INFOHASH = "0123456789abcdef0123456789abcdef01234567"
MAGNET = f"magnet:?xt=urn:btih:{INFOHASH}&dn=Fixture.Release"
TORRENT_BYTES = b"d8:announce13:https://track4:infod4:name7:fixtureee"


def _search_payload(*, download_url: str | None = None) -> list[dict[str, object]]:
    return [
        {
            "title": "Fixture.Release.2026.1080p",
            "indexer": "Fixture Torrent Indexer",
            "protocol": "torrent",
            "guid": "fixture-magnet-guid",
            "infoHash": INFOHASH,
            "magnetUrl": MAGNET,
            "infoUrl": "https://indexer.example.test/releases/magnet?api_key=source-page-secret#details",
        },
        {
            "title": "Fixture.Release.2026.Remux",
            "indexer": "Fixture Torrent Indexer",
            "protocol": "torrent",
            "guid": "fixture-torrent-guid",
            "downloadUrl": download_url
            or f"{BASE_URL}/download/fixture.torrent?passkey={DOWNLOAD_SECRET}",
            "infoUrl": "https://indexer.example.test/releases/torrent?token=secret",
        },
        {
            "title": "Fixture.Release.2026.Usenet",
            "indexer": "Fixture Usenet Indexer",
            "protocol": "usenet",
            "guid": "fixture-usenet-guid",
            "downloadUrl": f"{BASE_URL}/download/fixture.nzb",
        },
    ]


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
        if request.url.path == "/reverse/prowlarr/api/v1/system/status":
            return httpx.Response(200, json={"version": "2.0.0"})
        if request.url.path == "/reverse/prowlarr/api/v1/search":
            return httpx.Response(200, json=_search_payload())
        if request.url.path == "/reverse/prowlarr/download/fixture.torrent":
            return httpx.Response(200, content=TORRENT_BYTES)
        return httpx.Response(404)


def _module(
    clients: RecordingClientFactory | None = None,
    *,
    limits: ProwlarrLimits | None = None,
):
    return registration(
        client_factory=clients or RecordingClientFactory(),
        limits=limits or ProwlarrLimits(),
    )


def _environment(**overrides: str) -> dict[str, str]:
    return {
        "PROWLARR_URL": BASE_URL,
        "PROWLARR_API_KEY": API_KEY,
        "UNDECLARED_SECRET": "must-not-be-visible",
        **overrides,
    }


def _expected_candidates() -> tuple[ReleaseCandidate, ReleaseCandidate]:
    # The byte value is provider-private. It is deterministic only in the fixture package.
    module = _module()
    provider = module.build(resolve_module_environment(module.manifest, _environment()))
    try:
        return provider.search(ReleaseSearchQuery(query="Fixture", limit=10))  # type: ignore[return-value]
    finally:
        provider.close()


def test_prowlarr_wheel_is_independent_versioned_and_contains_declared_resources(
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
            "media-finder-release-prowlarr",
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

    package = "media_finder_release_prowlarr"
    assert {
        f"{package}/__init__.py",
        f"{package}/module.toml",
        f"{package}/py.typed",
        f"{package}/translations/en.json",
        f"{package}/translations/ru.json",
        f"{package}/fixtures/conformance.json",
        f"{package}/fixtures/search.json",
        f"{package}/fixtures/fixture.torrent",
    } <= names
    requirements = tuple(metadata.get_all("Requires-Dist", []))
    assert any(value.lower().startswith("media-finder-module-sdk") for value in requirements)
    assert any(value.lower().startswith("httpx") for value in requirements)
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
            "import media_finder_release_prowlarr as module",
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


def test_prowlarr_manifest_declares_exact_environment_and_public_sdk_only() -> None:
    package = PACKAGE_ROOT / "src/media_finder_release_prowlarr"
    manifest = load_manifest(package / "module.toml")

    assert manifest.module_id == "prowlarr"
    assert manifest.module_kind is ModuleKind.RELEASE_PROVIDER
    assert manifest.capabilities == {"search", "resolve", "magnet", "torrent"}
    assert manifest.environment == (
        EnvironmentVariableSpec(
            name="PROWLARR_URL",
            required=True,
            secret=False,
            description_key="module.prowlarr.environment.url",
        ),
        EnvironmentVariableSpec(
            name="PROWLARR_API_KEY",
            required=True,
            secret=True,
            description_key="module.prowlarr.environment.api_key",
        ),
    )
    assert manifest.attribution is None

    forbidden = (
        "media_finder_core",
        "media_finder_control",
        "media_finder_metadata_manual",
        "media_finder_metadata_tmdb",
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


def test_prowlarr_registration_passes_public_conformance_and_closes_resources() -> None:
    fixture_bytes = (
        PACKAGE_ROOT / "src/media_finder_release_prowlarr/fixtures/conformance.json"
    ).read_bytes()
    serialized = parse_serialized_conformance_fixture(fixture_bytes)
    assert isinstance(serialized, SerializedReleaseProviderConformance)
    clients = RecordingClientFactory()
    module = _module(clients)
    expected = _expected_candidates()
    assert len(expected) == 2
    assert tuple(candidate.snapshot.model_dump(mode="json") for candidate in expected) == tuple(
        result.snapshot.model_dump(mode="json") for result in serialized.success.results
    )
    provider = _module().build(resolve_module_environment(module.manifest, _environment()))
    try:
        candidates = provider.search(serialized.success.query)
        resolved = tuple(provider.resolve(candidate.selection) for candidate in candidates)
    finally:
        provider.close()
    descriptors = tuple(
        ArtifactDescriptor(
            kind=artifact.kind,
            byte_length=len(
                artifact.uri.encode("utf-8")
                if isinstance(artifact, MagnetArtifact)
                else artifact.content()
            ),
            sha256=hashlib.sha256(
                artifact.uri.encode("utf-8")
                if isinstance(artifact, MagnetArtifact)
                else artifact.content()
            ).hexdigest(),
        )
        for artifact in resolved
    )
    assert descriptors == tuple(
        resolved_fixture.artifact for resolved_fixture in serialized.success.resolved_artifacts
    )
    assert API_KEY.encode() not in fixture_bytes
    assert DOWNLOAD_SECRET.encode() not in fixture_bytes
    assert BASE_URL.encode() not in fixture_bytes
    assert MAGNET.encode() not in fixture_bytes
    assert TORRENT_BYTES not in fixture_bytes
    assert all(candidate.selection.payload() not in fixture_bytes for candidate in expected)
    missing = serialized.missing_configuration
    assert missing.applicable is True
    with pytest.raises(ModuleError) as missing_error:
        resolve_module_environment(module.manifest, {})
    assert missing_error.value.code == missing.error.code
    assert missing_error.value.category == missing.error.category
    assert dict(missing_error.value.safe_details) == dict(missing.error.safe_details)

    failures = {failure.operation: failure.error for failure in serialized.stable_failures}

    assert_release_registration_conforms(
        module,
        ReleaseConformanceFixture(
            environment=_environment(),
            query=serialized.success.query,
            expected_candidates=expected,
            expected_artifact=MagnetArtifact(uri=MAGNET),
            invalid_selection=PrivateReleaseSelection.from_bytes(b"not-provider-selection"),
            expected_error_code=failures["resolve-invalid-selection"].code,
        ),
    )

    invalid_provider = module.build(resolve_module_environment(module.manifest, _environment()))
    try:
        with pytest.raises(ModuleError) as invalid_selection:
            invalid_provider.resolve(PrivateReleaseSelection.from_bytes(b"not-provider-selection"))
    finally:
        invalid_provider.close()
    assert (
        ModuleErrorData.from_error(invalid_selection.value) == failures["resolve-invalid-selection"]
    )

    assert clients.clients
    assert all(client.is_closed for client in clients.clients)
    assert all(request.url.host == "prowlarr.example.test" for request in clients.requests)
    assert all(request.url.scheme == "https" for request in clients.requests)
    assert all(request.url.path.startswith("/reverse/prowlarr/") for request in clients.requests)
    assert all(request.headers["x-api-key"] == API_KEY for request in clients.requests)
    rendered = repr(clients.requests)
    assert "UNDECLARED_SECRET" not in rendered
    assert "must-not-be-visible" not in rendered


def test_prowlarr_search_is_torrent_only_bounded_and_keeps_selection_opaque() -> None:
    module = _module()
    provider = module.build(resolve_module_environment(module.manifest, _environment()))

    try:
        candidates = provider.search(ReleaseSearchQuery(query="Fixture", limit=1))
    finally:
        provider.close()
        provider.close()

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.snapshot.title == "Fixture.Release.2026.1080p"
    assert candidate.snapshot.indexer == "Fixture Torrent Indexer"
    assert "Usenet" not in candidate.snapshot.title
    assert isinstance(candidate.selection, PrivateReleaseSelection)
    assert "magnet" not in repr(candidate.selection).casefold()
    assert DOWNLOAD_SECRET not in repr(candidate.selection)
    assert not hasattr(candidate.selection, "model_dump")
    with pytest.raises(ValueError, match="release_selection_too_large"):
        PrivateReleaseSelection.from_bytes(b"x" * (64 * 1024 + 1))


def test_prowlarr_resolves_magnet_and_same_base_path_torrent_in_memory() -> None:
    clients = RecordingClientFactory()
    module = _module(clients)
    provider = module.build(resolve_module_environment(module.manifest, _environment()))

    try:
        candidates = provider.search(ReleaseSearchQuery(query="Fixture", limit=10))
        magnet = provider.resolve(candidates[0].selection)
        torrent = provider.resolve(candidates[1].selection)
    finally:
        provider.close()
        provider.close()

    assert magnet == MagnetArtifact(uri=MAGNET)
    assert isinstance(torrent, TorrentArtifact)
    assert torrent.content() == TORRENT_BYTES
    assert DOWNLOAD_SECRET not in repr(torrent)
    assert not hasattr(torrent, "model_dump")
    assert [request.url.path for request in clients.requests] == [
        "/reverse/prowlarr/api/v1/search",
        "/reverse/prowlarr/download/fixture.torrent",
    ]
    assert clients.requests[-1].url.query == f"passkey={DOWNLOAD_SECRET}".encode()
    assert all(client.is_closed for client in clients.clients)


@pytest.mark.parametrize(
    "url",
    (
        "prowlarr.example.test/reverse/prowlarr",
        "ftp://prowlarr.example.test/reverse/prowlarr",
        "https://user:password@prowlarr.example.test/reverse/prowlarr",
        "https://prowlarr.example.test/reverse/prowlarr?api_key=secret",
        "https://prowlarr.example.test/reverse/prowlarr#fragment",
        "https://prowlarr.example.test/reverse/%2e%2e/private",
    ),
)
def test_prowlarr_rejects_unsafe_configured_urls_before_http(url: str) -> None:
    clients = RecordingClientFactory()
    module = _module(clients)
    environment = resolve_module_environment(
        module.manifest,
        {"PROWLARR_URL": url, "PROWLARR_API_KEY": API_KEY},
    )

    with pytest.raises(ModuleError) as captured:
        module.build(environment)

    assert captured.value.code == "prowlarr_configuration_invalid"
    assert clients.requests == []
    assert all(client.is_closed for client in clients.clients)
    assert API_KEY not in f"{captured.value!s} {captured.value!r}"


@pytest.mark.parametrize(
    "download_url",
    (
        "https://attacker.example.test/reverse/prowlarr/download/fixture.torrent",
        "https://prowlarr.example.test/outside/fixture.torrent",
        "https://prowlarr.example.test/reverse/prowlarr/%2e%2e/private/fixture.torrent",
        "https://user:password@prowlarr.example.test/reverse/prowlarr/download/fixture.torrent",
    ),
)
def test_prowlarr_rejects_downloads_outside_configured_origin_and_base_path(
    download_url: str,
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/reverse/prowlarr/api/v1/search":
            return httpx.Response(200, json=_search_payload(download_url=download_url))
        return httpx.Response(200, json={})

    clients = RecordingClientFactory(respond)
    module = _module(clients)
    provider = module.build(resolve_module_environment(module.manifest, _environment()))

    try:
        candidates = provider.search(ReleaseSearchQuery(query="Fixture", limit=10))
        with pytest.raises(ModuleError) as captured:
            provider.resolve(candidates[1].selection)
    finally:
        provider.close()

    assert captured.value.code == "release_download_origin_rejected"
    assert len(clients.requests) == 1


def test_prowlarr_enforces_response_result_and_torrent_limits() -> None:
    serialized = parse_serialized_conformance_fixture(
        (PACKAGE_ROOT / "src/media_finder_release_prowlarr/fixtures/conformance.json").read_bytes()
    )
    assert isinstance(serialized, SerializedReleaseProviderConformance)
    failures = {failure.operation: failure.error for failure in serialized.stable_failures}

    result_limits = ProwlarrLimits(
        max_json_bytes=16 * 1024,
        max_search_results=1,
        max_torrent_bytes=16,
    )

    def too_many(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json=_search_payload()[:2])
        return httpx.Response(200, json={})

    module = _module(RecordingClientFactory(too_many), limits=result_limits)
    provider = module.build(resolve_module_environment(module.manifest, _environment()))
    try:
        with pytest.raises(ModuleError) as result_error:
            provider.search(ReleaseSearchQuery(query="Fixture", limit=10))
    finally:
        provider.close()
    assert ModuleErrorData.from_error(result_error.value) == failures["search-result-limit"]

    def too_large_json(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/search"):
            return httpx.Response(200, content=b"[" + b" " * 300 + b"]")
        return httpx.Response(200, json={})

    json_limits = ProwlarrLimits(
        max_json_bytes=256,
        max_search_results=10,
        max_torrent_bytes=16,
    )
    module = _module(RecordingClientFactory(too_large_json), limits=json_limits)
    provider = module.build(resolve_module_environment(module.manifest, _environment()))
    try:
        with pytest.raises(ModuleError) as json_error:
            provider.search(ReleaseSearchQuery(query="Fixture", limit=10))
    finally:
        provider.close()
    assert ModuleErrorData.from_error(json_error.value) == failures["search-response-limit"]

    def too_large_torrent(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json=_search_payload()[1:2])
        return httpx.Response(200, content=b"12345")

    torrent_limits = ProwlarrLimits(
        max_json_bytes=16 * 1024,
        max_search_results=10,
        max_torrent_bytes=4,
    )
    module = _module(RecordingClientFactory(too_large_torrent), limits=torrent_limits)
    provider = module.build(resolve_module_environment(module.manifest, _environment()))
    try:
        candidate = provider.search(ReleaseSearchQuery(query="Fixture", limit=10))[0]
        with pytest.raises(ModuleError) as torrent_error:
            provider.resolve(candidate.selection)
    finally:
        provider.close()
    assert ModuleErrorData.from_error(torrent_error.value) == failures["resolve-torrent-limit"]


def test_prowlarr_failures_and_logs_are_secret_safe(caplog: pytest.LogCaptureFixture) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        raise RuntimeError(
            f"failed {request.url}/passkey/{DOWNLOAD_SECRET}?api_key={API_KEY}#fragment"
        )

    caplog.set_level(logging.DEBUG)
    clients = RecordingClientFactory(fail)
    module = _module(clients)
    provider = module.build(resolve_module_environment(module.manifest, _environment()))

    try:
        with pytest.raises(ModuleError) as captured:
            provider.search(ReleaseSearchQuery(query="Fixture", limit=10))
    finally:
        provider.close()
        provider.close()

    rendered = f"{captured.value!s} {captured.value!r} {captured.value.safe_details!r}"
    logs = caplog.text
    assert captured.value.code == "release_provider_unavailable"
    for secret in (API_KEY, DOWNLOAD_SECRET, "passkey", "api_key", "fragment"):
        assert secret not in rendered
        assert secret not in logs
    assert all(client.is_closed for client in clients.clients)


def test_prowlarr_serialized_redaction_probes_cross_env_selection_artifact_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    serialized = parse_serialized_conformance_fixture(
        (PACKAGE_ROOT / "src/media_finder_release_prowlarr/fixtures/conformance.json").read_bytes()
    )
    assert isinstance(serialized, SerializedReleaseProviderConformance)
    probes = serialized.redaction_probes
    caplog.set_level(logging.DEBUG)

    def fail(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-api-key"] == probes.environment_value
        raise RuntimeError(" ".join(probes.model_dump().values()))

    failure_module = _module(RecordingClientFactory(fail))
    failure_provider = failure_module.build(
        resolve_module_environment(
            failure_module.manifest,
            _environment(PROWLARR_API_KEY=probes.environment_value),
        )
    )
    try:
        with pytest.raises(ModuleError) as upstream_error:
            failure_provider.search(ReleaseSearchQuery(query="Fixture", limit=10))
        with pytest.raises(ModuleError) as selection_error:
            failure_provider.resolve(
                PrivateReleaseSelection.from_bytes(probes.private_selection.encode())
            )
    finally:
        failure_provider.close()

    artifact_body = probes.artifact_body.encode()

    def serve_probe_artifact(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/search"):
            return httpx.Response(200, json=_search_payload()[1:2])
        if request.url.path.endswith("/fixture.torrent"):
            return httpx.Response(200, content=artifact_body)
        return httpx.Response(200, json={"version": "2.0.0"})

    artifact_module = _module(RecordingClientFactory(serve_probe_artifact))
    artifact_provider = artifact_module.build(
        resolve_module_environment(artifact_module.manifest, _environment())
    )
    try:
        candidate = artifact_provider.search(ReleaseSearchQuery(query="Fixture", limit=10))[0]
        artifact = artifact_provider.resolve(candidate.selection)
    finally:
        artifact_provider.close()
    assert isinstance(artifact, TorrentArtifact)
    assert artifact.content() == artifact_body
    descriptor = ArtifactDescriptor(
        kind="torrent",
        byte_length=len(artifact.content()),
        sha256=hashlib.sha256(artifact.content()).hexdigest(),
    )

    safe_public = " ".join(
        (
            ModuleErrorData.from_error(upstream_error.value).model_dump_json(),
            ModuleErrorData.from_error(selection_error.value).model_dump_json(),
            candidate.snapshot.model_dump_json(),
            descriptor.model_dump_json(),
            caplog.text,
        )
    )
    for probe in probes.model_dump().values():
        assert probe not in safe_public


def test_torrent_download_url_is_redacted_from_httpx_info_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="httpx")
    clients = RecordingClientFactory()
    provider = _module(clients).build(
        resolve_module_environment(_module().manifest, _environment())
    )

    try:
        torrent = provider.search(ReleaseSearchQuery(query="Fixture", limit=10))[1]
        provider.resolve(torrent.selection)
    finally:
        provider.close()

    assert DOWNLOAD_SECRET not in caplog.text
    assert "passkey=" not in caplog.text
    assert f"{BASE_URL}/download/fixture.torrent" not in caplog.text


def test_live_validation_rejects_an_oversized_status_response() -> None:
    def oversized(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/api/v1/system/status")
        return httpx.Response(200, text="{}" + " " * (2 * 1024 * 1024))

    provider = _module(RecordingClientFactory(oversized)).build(
        resolve_module_environment(_module().manifest, _environment())
    )
    try:
        with pytest.raises(ModuleError, match="prowlarr_configuration_invalid"):
            provider.validate()
    finally:
        provider.close()


def test_source_page_snapshot_never_persists_untrusted_paths_or_queries() -> None:
    opaque_path = "opaque-release-secret-1234567890"

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/v1/search"):
            payload = _search_payload()
            payload[0]["infoUrl"] = (
                f"https://indexer.example.test/torrent/{opaque_path}?passkey={DOWNLOAD_SECRET}"
            )
            return httpx.Response(200, json=payload[:1])
        return httpx.Response(200, json={})

    provider = _module(RecordingClientFactory(respond)).build(
        resolve_module_environment(_module().manifest, _environment())
    )
    try:
        candidate = provider.search(ReleaseSearchQuery(query="Fixture", limit=10))[0]
    finally:
        provider.close()

    assert str(candidate.snapshot.source_page_url) == "https://indexer.example.test/"
    rendered = candidate.snapshot.model_dump_json()
    assert opaque_path not in rendered
    assert DOWNLOAD_SECRET not in rendered


@pytest.mark.parametrize(
    "source_page_url",
    [
        "http://printer.local/private?passkey=secret",
        "http://localhost/private",
        "http://127.0.0.1/private",
    ],
)
def test_source_page_snapshot_rejects_non_public_hosts(source_page_url: str) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/v1/search"):
            payload = _search_payload()
            payload[0]["infoUrl"] = source_page_url
            return httpx.Response(200, json=payload[:1])
        return httpx.Response(200, json={})

    provider = _module(RecordingClientFactory(respond)).build(
        resolve_module_environment(_module().manifest, _environment())
    )
    try:
        candidate = provider.search(ReleaseSearchQuery(query="Fixture", limit=10))[0]
    finally:
        provider.close()

    assert candidate.snapshot.source_page_url is None


def test_release_snapshot_rejects_credential_like_guid() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/v1/search"):
            payload = _search_payload()
            payload[0]["guid"] = "token-123"
            return httpx.Response(200, json=payload[:1])
        return httpx.Response(200, json={})

    provider = _module(RecordingClientFactory(respond)).build(
        resolve_module_environment(_module().manifest, _environment())
    )
    try:
        candidate = provider.search(ReleaseSearchQuery(query="Fixture", limit=10))[0]
    finally:
        provider.close()

    assert candidate.snapshot.guid is None
