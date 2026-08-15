"""Isolated Prowlarr release-provider module contract."""

from __future__ import annotations

import ast
import email
import logging
import os
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
    EnvironmentVariableSpec,
    MagnetArtifact,
    ModuleError,
    ModuleKind,
    PrivateReleaseSelection,
    ReleaseCandidate,
    ReleaseConformanceFixture,
    ReleaseSearchQuery,
    SafeReleaseSnapshot,
    TorrentArtifact,
    assert_release_registration_conforms,
    load_manifest,
    resolve_module_environment,
)

ROOT = Path(__file__).parents[4]
PACKAGE_ROOT = ROOT / "packages" / "modules" / "release-prowlarr"
UV = ROOT / ".venv" / "Scripts" / "uv.exe"
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


def _environment() -> dict[str, str]:
    return {
        "PROWLARR_URL": BASE_URL,
        "PROWLARR_API_KEY": API_KEY,
        "UNDECLARED_SECRET": "must-not-be-visible",
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
            "--no-build-isolation",
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
    clients = RecordingClientFactory()
    module = _module(clients)
    expected = _expected_candidates()
    assert len(expected) == 2
    assert expected[0].snapshot == SafeReleaseSnapshot(
        title="Fixture.Release.2026.1080p",
        indexer="Fixture Torrent Indexer",
        guid="fixture-magnet-guid",
        infohash=INFOHASH,
        source_page_url="https://indexer.example.test/releases/magnet",
    )
    assert expected[1].snapshot == SafeReleaseSnapshot(
        title="Fixture.Release.2026.Remux",
        indexer="Fixture Torrent Indexer",
        guid="fixture-torrent-guid",
        source_page_url="https://indexer.example.test/releases/torrent",
    )

    assert_release_registration_conforms(
        module,
        ReleaseConformanceFixture(
            environment=_environment(),
            query=ReleaseSearchQuery(query="Fixture", limit=10),
            expected_candidates=expected,
            expected_artifact=MagnetArtifact(uri=MAGNET),
            invalid_selection=PrivateReleaseSelection.from_bytes(b"not-provider-selection"),
            expected_error_code="release_selection_invalid",
        ),
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
    assert result_error.value.code == "release_result_limit_exceeded"

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
    assert json_error.value.code == "release_response_too_large"

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
    assert torrent_error.value.code == "release_torrent_too_large"


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
