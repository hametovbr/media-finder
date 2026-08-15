import httpx
import pytest
from pydantic import ValidationError

from media_finder.modules.qbittorrent import (
    HttpxQbittorrentTransport,
    QbittorrentClient,
    QbittorrentConfig,
)
from media_finder.sdk.conformance import assert_client_conforms
from media_finder.sdk.errors import ModuleError
from media_finder.sdk.types import MagnetArtifact, TorrentArtifact


class FakeQbittorrentTransport:
    def __init__(self) -> None:
        self.auth: tuple[str, str] | None = None
        self.submissions: list[tuple[str, object, str, str]] = []
        self.fail_with: Exception | None = None
        self.lookup_failure: Exception | None = None

    def authenticate(self, username: str, password: str) -> None:
        self.auth = (username, password)

    def list_categories(self) -> dict[str, str]:
        return {"manual-radarr": "/downloads/movies", "anime": "/downloads/anime"}

    def add_magnet(self, uri: str, category: str, tag: str) -> str:
        if self.fail_with:
            raise self.fail_with
        self.submissions.append(("magnet", uri, category, tag))
        return "task-magnet"

    def add_torrent(self, content: bytes, category: str, tag: str) -> str:
        if self.fail_with:
            raise self.fail_with
        self.submissions.append(("torrent", content, category, tag))
        return "task-torrent"

    def find_by_tag(self, tag: str) -> list[dict[str, str]]:
        if self.lookup_failure:
            raise self.lookup_failure
        return [
            {"hash": f"hash-{index}", "tags": submitted_tag}
            for index, (_, _, _, submitted_tag) in enumerate(self.submissions)
            if submitted_tag == tag
        ]


def build_client(
    transport: FakeQbittorrentTransport | None = None,
) -> tuple[QbittorrentClient, FakeQbittorrentTransport]:
    native = transport or FakeQbittorrentTransport()
    secrets = {"QB_USER": "fixture-user", "QB_PASS": "top-secret-password"}
    client = QbittorrentClient(
        QbittorrentConfig(
            base_url="https://qb.example.test",
            username_ref="env:QB_USER",
            password_ref="env:QB_PASS",
        ),
        native,
        secret_resolver=lambda reference: secrets[reference.removeprefix("env:")],
    )
    return client, native


def test_qbittorrent_client_conforms_and_maps_native_fields_exactly() -> None:
    client, transport = build_client()

    assert_client_conforms(client)
    destinations = client.list_destinations()
    assert [(item.key, item.label) for item in destinations] == [
        ("anime", "anime"),
        ("manual-radarr", "manual-radarr"),
    ]

    correlation = "mf-acq-47e26ca2-f393-4a00-b33a-902d41d49714"
    client.submit(
        MagnetArtifact(uri="magnet:?xt=urn:btih:" + "a" * 40),
        "anime",
        correlation,
    )
    client.submit(TorrentArtifact(content=b"torrent-bytes"), "manual-radarr", correlation)

    assert transport.submissions[-2:] == [
        (
            "magnet",
            "magnet:?xt=urn:btih:" + "a" * 40,
            "anime",
            correlation,
        ),
        ("torrent", b"torrent-bytes", "manual-radarr", correlation),
    ]
    found = client.find_by_correlation(correlation)
    assert found.found is True
    assert found.correlation == correlation
    assert transport.auth == ("fixture-user", "top-secret-password")


def test_qbittorrent_config_requires_secret_references_and_errors_are_safe() -> None:
    with pytest.raises(ValidationError):
        QbittorrentConfig(
            base_url="https://qb.example.test",
            username_ref="literal-user",
            password_ref="literal-password",
        )
    with pytest.raises(ValidationError):
        QbittorrentConfig(
            base_url="https://user:password@qb.example.test/api?token=secret#fragment",
            username_ref="env:QB_USER",
            password_ref="env:QB_PASS",
        )

    transport = FakeQbittorrentTransport()
    transport.fail_with = RuntimeError("top-secret-password at /download/passkey")
    client, _ = build_client(transport)
    with pytest.raises(ModuleError) as rejected:
        client.submit(MagnetArtifact(uri="magnet:?xt=secret"), "anime", "mf-acq-safe")

    assert rejected.value.code == "download_client_submission_failed"
    assert "secret" not in str(rejected.value).casefold()
    assert rejected.value.safe_details == {}


def test_qbittorrent_timeout_and_lookup_failures_are_safe_and_unambiguous() -> None:
    transport = FakeQbittorrentTransport()
    client, _ = build_client(transport)
    transport.fail_with = TimeoutError("passkey=must-not-escape")
    with pytest.raises(ModuleError) as timed_out:
        client.submit(MagnetArtifact(uri="magnet:?xt=secret"), "anime", "mf-acq-timeout")
    assert timed_out.value.code == "submission_timeout"
    assert "passkey" not in str(timed_out.value)

    transport.lookup_failure = TimeoutError("credential=must-not-escape")
    with pytest.raises(ModuleError) as inconclusive:
        client.find_by_correlation("mf-acq-timeout")
    assert inconclusive.value.code == "correlation_lookup_inconclusive"
    assert "credential" not in str(inconclusive.value)


def test_http_transport_uses_qbittorrent_web_api_fields() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/v2/auth/login":
            return httpx.Response(200, text="Ok.")
        if request.url.path == "/api/v2/torrents/categories":
            return httpx.Response(
                200,
                json={"anime": {"name": "anime", "savePath": "/downloads/anime"}},
            )
        if request.url.path == "/api/v2/torrents/info":
            return httpx.Response(200, json=[{"hash": "a" * 40, "tags": "mf-acq-wire"}])
        return httpx.Response(200, text="Ok.")

    native = HttpxQbittorrentTransport(
        "https://qb.example.test", httpx.Client(transport=httpx.MockTransport(handler))
    )
    native.authenticate("user", "password")
    assert native.list_categories() == {"anime": "/downloads/anime"}
    native.add_magnet("magnet:?xt=urn:btih:" + "a" * 40, "anime", "mf-acq-wire")
    native.add_torrent(b"torrent-bytes", "anime", "mf-acq-wire")
    assert native.find_by_tag("mf-acq-wire") == [{"hash": "a" * 40, "tags": "mf-acq-wire"}]

    add_requests = [request for request in requests if request.url.path == "/api/v2/torrents/add"]
    assert len(add_requests) == 2
    assert b"category=anime" in add_requests[0].content
    assert b"tags=mf-acq-wire" in add_requests[0].content
    assert b"urls=magnet" in add_requests[0].content
    assert b"torrent-bytes" in add_requests[1].content
    lookup = requests[-1]
    assert lookup.url.params["tag"] == "mf-acq-wire"
