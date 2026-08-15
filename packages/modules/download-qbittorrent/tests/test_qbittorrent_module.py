"""Isolated qBittorrent download-client module contract."""

from __future__ import annotations

import ast
import email
import logging
import os
import subprocess
import sys
import traceback
import zipfile
from collections.abc import Callable
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from media_finder_download_qbittorrent import registration
from media_finder_sdk import (
    CorrelationResult,
    DownloadClientConformanceFixture,
    DownloadDestination,
    EnvironmentVariableSpec,
    MagnetArtifact,
    ModuleError,
    ModuleFailureCategory,
    ModuleKind,
    SubmissionResult,
    TorrentArtifact,
    assert_download_registration_conforms,
    load_manifest,
    resolve_module_environment,
)

ROOT = Path(__file__).parents[4]
PACKAGE_ROOT = ROOT / "packages" / "modules" / "download-qbittorrent"
UV = ROOT / ".venv" / "Scripts" / "uv.exe"
UV_CACHE = ROOT / ".tools" / "uv-cache"
BASE_URL = "https://qbittorrent.example.test/reverse/qb"
USERNAME = "qb-fixture-user-never-log"
PASSWORD = "qb-fixture-password-never-log"
CORRELATION = "mf-acq-47e26ca2-f393-4a00-b33a-902d41d49714"
INFOHASH = "0123456789abcdef0123456789abcdef01234567"
MAGNET = f"magnet:?xt=urn:btih:{INFOHASH}&dn=Fixture.Release"
TORRENT_BYTES = b"d8:announce13:https://track4:infod4:name7:fixtureee"


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
        if request.url.path == "/reverse/qb/api/v2/auth/login":
            return httpx.Response(200, text="Ok.", headers={"set-cookie": "SID=qb; Path=/"})
        if request.url.path == "/reverse/qb/api/v2/torrents/categories":
            return httpx.Response(
                200,
                json={
                    "anime": {"name": "anime", "savePath": "/downloads/anime"},
                    "manual-radarr": {
                        "name": "manual-radarr",
                        "savePath": "/downloads/movies",
                    },
                },
            )
        if request.url.path == "/reverse/qb/api/v2/torrents/add":
            return httpx.Response(200, text="Ok.")
        if request.url.path == "/reverse/qb/api/v2/torrents/info":
            return httpx.Response(
                200,
                json=[
                    {"hash": "wrong-near-match", "tags": f"prefix-{CORRELATION}"},
                    {"hash": INFOHASH, "tags": f"other, {CORRELATION}"},
                ],
            )
        return httpx.Response(404)


def _environment(**overrides: str) -> dict[str, str]:
    return {
        "QBITTORRENT_URL": BASE_URL,
        "QBITTORRENT_USERNAME": USERNAME,
        "QBITTORRENT_PASSWORD": PASSWORD,
        "UNDECLARED_SECRET": "must-not-be-visible",
        **overrides,
    }


def _module(clients: RecordingClientFactory | None = None):
    return registration(client_factory=clients or RecordingClientFactory())


def _client(clients: RecordingClientFactory):
    module = _module(clients)
    return module.build(resolve_module_environment(module.manifest, _environment()))


def test_qbittorrent_wheel_is_independent_versioned_and_contains_declared_resources(
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
            "media-finder-download-qbittorrent",
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

    package = "media_finder_download_qbittorrent"
    assert {
        f"{package}/__init__.py",
        f"{package}/module.toml",
        f"{package}/py.typed",
        f"{package}/translations/en.json",
        f"{package}/translations/ru.json",
        f"{package}/fixtures/conformance.json",
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
            "import media_finder_download_qbittorrent as module",
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


def test_qbittorrent_manifest_declares_exact_environment_and_public_sdk_only() -> None:
    package = PACKAGE_ROOT / "src/media_finder_download_qbittorrent"
    manifest = load_manifest(package / "module.toml")

    assert manifest.module_id == "qbittorrent"
    assert manifest.module_kind is ModuleKind.DOWNLOAD_CLIENT
    assert manifest.capabilities == {
        "destinations",
        "submit",
        "correlation",
        "magnet",
        "torrent",
    }
    assert manifest.environment == (
        EnvironmentVariableSpec(
            name="QBITTORRENT_URL",
            required=True,
            secret=False,
            description_key="module.qbittorrent.environment.url",
        ),
        EnvironmentVariableSpec(
            name="QBITTORRENT_USERNAME",
            required=True,
            secret=True,
            description_key="module.qbittorrent.environment.username",
        ),
        EnvironmentVariableSpec(
            name="QBITTORRENT_PASSWORD",
            required=True,
            secret=True,
            description_key="module.qbittorrent.environment.password",
        ),
    )
    assert manifest.attribution is None

    forbidden = (
        "media_finder.",
        "media_finder_core",
        "media_finder_control",
        "media_finder_metadata_manual",
        "media_finder_metadata_tmdb",
        "media_finder_release_prowlarr",
        "media_finder_builtin_ui",
        "sqlalchemy",
        "alembic",
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


def test_qbittorrent_registration_conforms_and_uses_confined_web_api() -> None:
    clients = RecordingClientFactory()
    module = _module(clients)
    assert_download_registration_conforms(
        module,
        DownloadClientConformanceFixture(
            environment=_environment(),
            expected_destinations=(
                DownloadDestination(key="anime", label="anime"),
                DownloadDestination(key="manual-radarr", label="manual-radarr"),
            ),
            artifacts=(
                MagnetArtifact(uri=MAGNET),
                TorrentArtifact.from_bytes(TORRENT_BYTES),
            ),
            destination="anime",
            invalid_destination="removed",
            correlation=CORRELATION,
            expected_submission=SubmissionResult(
                accepted=True,
                correlation=CORRELATION,
            ),
            expected_correlation=CorrelationResult(
                found=True,
                correlation=CORRELATION,
                external_task_id=INFOHASH,
            ),
            expected_error_code="download_destination_unavailable",
        ),
    )

    assert clients.clients and all(client.is_closed for client in clients.clients)
    assert all(request.url.host == "qbittorrent.example.test" for request in clients.requests)
    assert all(request.url.path.startswith("/reverse/qb/") for request in clients.requests)
    assert all(request.url.scheme == "https" for request in clients.requests)
    rendered = repr(clients.requests)
    assert "UNDECLARED_SECRET" not in rendered
    assert "must-not-be-visible" not in rendered


def test_qbittorrent_reloads_live_categories_immediately_before_submission() -> None:
    category_calls = 0
    add_calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal category_calls, add_calls
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, text="Ok.")
        if request.url.path.endswith("/torrents/categories"):
            category_calls += 1
            category = "anime" if category_calls == 1 else "movies"
            return httpx.Response(200, json={category: {"name": category, "savePath": "/d"}})
        if request.url.path.endswith("/torrents/add"):
            add_calls += 1
            return httpx.Response(200, text="Ok.")
        return httpx.Response(404)

    client = _client(RecordingClientFactory(respond))
    try:
        assert client.list_destinations() == (DownloadDestination(key="anime", label="anime"),)
        with pytest.raises(ModuleError) as stale:
            client.submit(MagnetArtifact(uri=MAGNET), "anime", CORRELATION)
    finally:
        client.close()

    assert stale.value.category is ModuleFailureCategory.INVALID_REQUEST
    assert stale.value.code == "download_destination_unavailable"
    assert category_calls == 2
    assert add_calls == 0


def test_qbittorrent_preserves_exact_correlation_for_both_artifacts_and_lookup() -> None:
    clients = RecordingClientFactory()
    client = _client(clients)
    try:
        magnet_result = client.submit(MagnetArtifact(uri=MAGNET), "anime", CORRELATION)
        torrent_result = client.submit(
            TorrentArtifact.from_bytes(TORRENT_BYTES),
            "manual-radarr",
            CORRELATION,
        )
        found = client.find_by_correlation(CORRELATION)
    finally:
        client.close()
        client.close()

    assert magnet_result.correlation == CORRELATION
    assert torrent_result.correlation == CORRELATION
    assert found == CorrelationResult(
        found=True,
        correlation=CORRELATION,
        external_task_id=INFOHASH,
    )
    additions = [
        request for request in clients.requests if request.url.path.endswith("/torrents/add")
    ]
    assert len(additions) == 2
    magnet_form = parse_qs(additions[0].content.decode())
    assert magnet_form == {
        "urls": [MAGNET],
        "category": ["anime"],
        "tags": [CORRELATION],
    }
    multipart = additions[1].content
    assert TORRENT_BYTES in multipart
    assert f"\r\n\r\n{CORRELATION}\r\n".encode() in multipart
    assert b"\r\n\r\nmanual-radarr\r\n" in multipart
    lookup = next(
        request for request in clients.requests if request.url.path.endswith("/torrents/info")
    )
    assert lookup.url.params.get("tag") == CORRELATION


@pytest.mark.parametrize(
    "url",
    (
        "qbittorrent.example.test/reverse/qb",
        "ftp://qbittorrent.example.test/reverse/qb",
        "https://user:password@qbittorrent.example.test/reverse/qb",
        "https://qbittorrent.example.test/reverse/qb?token=secret",
        "https://qbittorrent.example.test/reverse/qb#fragment",
        "https://qbittorrent.example.test/reverse/%2e%2e/private",
    ),
)
def test_qbittorrent_rejects_unsafe_urls_before_authentication(url: str) -> None:
    clients = RecordingClientFactory()
    module = _module(clients)
    environment = resolve_module_environment(
        module.manifest,
        _environment(QBITTORRENT_URL=url),
    )

    with pytest.raises(ModuleError) as captured:
        module.build(environment)

    assert captured.value.category is ModuleFailureCategory.CONFIGURATION
    assert captured.value.code == "qbittorrent_configuration_invalid"
    assert clients.requests == []
    assert all(client.is_closed for client in clients.clients)
    rendered = f"{captured.value!s} {captured.value!r}"
    assert USERNAME not in rendered
    assert PASSWORD not in rendered


def test_qbittorrent_authentication_failure_is_standardized_and_secret_safe() -> None:
    upstream_body = f"rejected username={USERNAME} password={PASSWORD}"

    def reject_auth(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/auth/login")
        return httpx.Response(403, text=upstream_body)

    client = _client(RecordingClientFactory(reject_auth))
    try:
        with pytest.raises(ModuleError) as captured:
            client.validate()
    finally:
        client.close()

    assert captured.value.category is ModuleFailureCategory.CONFIGURATION
    assert captured.value.code == "download_client_authentication_failed"
    rendered = "".join(traceback.format_exception(captured.value))
    assert captured.value.__cause__ is None
    assert USERNAME not in rendered
    assert PASSWORD not in rendered
    assert upstream_body not in rendered


def test_qbittorrent_sessions_are_isolated_and_lifecycle_close_is_idempotent() -> None:
    clients = RecordingClientFactory()
    first = _client(clients)
    second = _client(clients)
    try:
        first.validate()
        second.validate()
    finally:
        first.close()
        first.close()
        second.close()
        second.close()

    login_requests = [
        request for request in clients.requests if request.url.path.endswith("/auth/login")
    ]
    assert len(clients.clients) == 2
    assert len(login_requests) == 2
    assert login_requests[0].headers.get("cookie") is None
    assert login_requests[-1].headers.get("cookie") is None
    assert all(client.is_closed for client in clients.clients)


def test_qbittorrent_timeout_and_lookup_failure_remain_ambiguous_without_retry() -> None:
    add_calls = 0
    lookup_calls = 0

    def time_out(request: httpx.Request) -> httpx.Response:
        nonlocal add_calls, lookup_calls
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, text="Ok.")
        if request.url.path.endswith("/torrents/categories"):
            return httpx.Response(200, json={"anime": {"savePath": "/downloads/anime"}})
        if request.url.path.endswith("/torrents/add"):
            add_calls += 1
            raise httpx.ReadTimeout(f"password={PASSWORD}")
        if request.url.path.endswith("/torrents/info"):
            lookup_calls += 1
            raise httpx.ReadTimeout(f"username={USERNAME}")
        return httpx.Response(404)

    client = _client(RecordingClientFactory(time_out))
    try:
        with pytest.raises(ModuleError) as submit_timeout:
            client.submit(MagnetArtifact(uri=MAGNET), "anime", CORRELATION)
        assert add_calls == 1
        assert lookup_calls == 0
        with pytest.raises(ModuleError) as lookup_timeout:
            client.find_by_correlation(CORRELATION)
    finally:
        client.close()

    assert submit_timeout.value.category is ModuleFailureCategory.TIMEOUT
    assert submit_timeout.value.code == "submission_timeout"
    assert lookup_timeout.value.category is ModuleFailureCategory.INCONCLUSIVE
    assert lookup_timeout.value.code == "correlation_lookup_inconclusive"
    assert add_calls == 1
    assert lookup_calls == 1
    rendered = "".join(
        traceback.format_exception(submit_timeout.value)
        + traceback.format_exception(lookup_timeout.value)
    )
    assert submit_timeout.value.__cause__ is None
    assert lookup_timeout.value.__cause__ is None
    assert USERNAME not in rendered
    assert PASSWORD not in rendered


def test_qbittorrent_failures_and_logs_never_disclose_credentials_or_artifacts(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_detail = f"{USERNAME} {PASSWORD} {MAGNET} {TORRENT_BYTES!r}"

    def fail_submission(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, text="Ok.")
        if request.url.path.endswith("/torrents/categories"):
            return httpx.Response(200, json={"anime": {"savePath": "/downloads/anime"}})
        raise RuntimeError(secret_detail)

    caplog.set_level(logging.DEBUG)
    client = _client(RecordingClientFactory(fail_submission))
    try:
        with pytest.raises(ModuleError) as captured:
            client.submit(MagnetArtifact(uri=MAGNET), "anime", CORRELATION)
    finally:
        client.close()
        client.close()

    assert captured.value.category is ModuleFailureCategory.UNAVAILABLE
    assert captured.value.code == "download_client_submission_failed"
    assert captured.value.safe_details == {}
    rendered = (
        f"{captured.value!s} {captured.value!r} "
        + "".join(traceback.format_exception(captured.value))
        + caplog.text
    )
    for secret in (USERNAME, PASSWORD, MAGNET, repr(TORRENT_BYTES)):
        assert secret not in rendered
