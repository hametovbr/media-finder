from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from media_finder.prowlarr import (
    ExpiredSearchToken,
    HttpxProwlarrTransport,
    ProwlarrAdapter,
    ProwlarrError,
    SearchResultCache,
)
from media_finder.sdk.types import MagnetArtifact, TorrentArtifact


class FakeProwlarrTransport:
    def __init__(self) -> None:
        self.fetched_urls: list[str] = []

    def search(self, query: str, filters: dict[str, str]) -> list[dict[str, object]]:
        assert query == "Fixture query"
        assert filters == {"indexerIds": "7", "categories": "2000"}
        return [
            {
                "protocol": "usenet",
                "title": "Must be filtered",
                "indexer": "Indexer",
                "downloadUrl": "https://indexer.invalid/secret/nzb",
            },
            {
                "protocol": "torrent",
                "title": "Magnet release",
                "indexer": "Torrent Indexer",
                "magnetUrl": "magnet:?xt=urn:btih:" + "A" * 40,
                "guid": "fixture.release:42",
                "guidIsPublic": True,
                "infoHash": "A" * 40,
                "infoUrl": "https://user:secret@example.test/releases/42?passkey=secret#x",
                "publicRoutePath": False,
            },
            {
                "protocol": "torrent",
                "title": "Torrent file release",
                "indexer": "Torrent Indexer",
                "downloadUrl": "https://indexer.invalid/download/secret-passkey",
                "guid": "https://indexer.invalid/download/secret-passkey",
                "guidIsPublic": False,
                "infoHash": "not-an-infohash",
                "infoUrl": "https://example.test/public/release/43?session=secret",
                "publicRoutePath": True,
                "normalizedPublicPath": "/public/release/43",
            },
        ]

    def fetch_torrent(self, url: str) -> bytes:
        self.fetched_urls.append(url)
        return b"d8:announce0:e"


def test_prowlarr_results_are_torrent_only_ephemeral_and_resolve_in_memory(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    cache = SearchResultCache(ttl=timedelta(minutes=5), clock=lambda: now)
    transport = FakeProwlarrTransport()
    adapter = ProwlarrAdapter(transport, cache)

    before = set(tmp_path.iterdir())
    results = adapter.search("Fixture query", {"indexerIds": "7", "categories": "2000"})

    assert [result.title for result in results] == [
        "Magnet release",
        "Torrent file release",
    ]
    assert len({result.token for result in results}) == 2
    assert all(len(result.token) >= 32 and "://" not in result.token for result in results)
    assert all("secret" not in repr(result) for result in results)
    assert results[0].snapshot.guid == "fixture.release:42"
    assert results[0].snapshot.infohash == "a" * 40
    assert results[0].snapshot.source_page_url == "https://example.test"
    assert results[1].snapshot.guid is None
    assert results[1].snapshot.infohash is None
    assert results[1].snapshot.source_page_url == "https://example.test"

    magnet = adapter.resolve(results[0].token)
    torrent = adapter.resolve(results[1].token)

    assert isinstance(magnet.artifact, MagnetArtifact)
    assert isinstance(torrent.artifact, TorrentArtifact)
    assert torrent.artifact.content == b"d8:announce0:e"
    assert transport.fetched_urls == ["https://indexer.invalid/download/secret-passkey"]
    assert set(tmp_path.iterdir()) == before


def test_search_tokens_expire_and_are_process_local() -> None:
    current = [datetime(2026, 1, 1, tzinfo=UTC)]
    transport = FakeProwlarrTransport()
    cache = SearchResultCache(ttl=timedelta(seconds=30), clock=lambda: current[0], max_entries=2)
    adapter = ProwlarrAdapter(transport, cache)
    token = adapter.search("Fixture query", {"indexerIds": "7", "categories": "2000"})[0].token

    current[0] += timedelta(seconds=31)
    with pytest.raises(ExpiredSearchToken) as expired:
        adapter.resolve(token)
    assert token not in str(expired.value)

    restarted = ProwlarrAdapter(
        transport,
        SearchResultCache(ttl=timedelta(minutes=5), clock=lambda: current[0]),
    )
    with pytest.raises(ExpiredSearchToken):
        restarted.resolve(token)


class AdversarialTransport(FakeProwlarrTransport):
    def search(self, query: str, filters: dict[str, str]) -> list[dict[str, object]]:
        return [
            {
                "protocol": "torrent",
                "title": "Adversarial",
                "indexer": "Indexer",
                "magnetUrl": "magnet:?xt=urn:btmh:" + "b" * 64,
                "guid": "https://user:pass@indexer.invalid/download?token=never-log",
                "guidIsPublic": True,
                "infoHash": "B" * 64,
                "infoUrl": "https://user:password@example.test/download/passkey-value?token=x#y",
                "publicRoutePath": True,
                "normalizedPublicPath": "/download/passkey-value",
            },
            {
                "protocol": "torrent",
                "title": "Origin fallback",
                "indexer": "Indexer",
                "magnetUrl": "magnet:?xt=urn:btih:" + "c" * 40,
                "guid": "bad%2Fguid",
                "guidIsPublic": True,
                "infoHash": "C" * 40,
                "infoUrl": "https://example.test/releases;session=never-log/42?q=never-log",
                "publicRoutePath": False,
            },
        ]


def test_release_snapshot_rejects_download_routes_and_secret_bearing_identifiers(
    caplog: pytest.LogCaptureFixture,
) -> None:
    results = ProwlarrAdapter(AdversarialTransport(), SearchResultCache()).search("Adversarial", {})

    first, second = results
    assert first.snapshot.guid is None
    assert first.snapshot.infohash == "b" * 64
    assert first.snapshot.source_page_url is None
    assert second.snapshot.guid is None
    assert second.snapshot.infohash == "c" * 40
    assert second.snapshot.source_page_url is None
    captured = caplog.text.casefold()
    assert "password" not in captured
    assert "never-log" not in captured
    assert "passkey-value" not in captured


def test_http_transport_uses_prowlarr_api_without_exposing_key() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["X-Api-Key"] == "prowlarr-secret"
        if request.url.path == "/api/v1/search":
            return httpx.Response(
                200,
                json=[
                    {
                        "protocol": "torrent",
                        "title": "Wire release",
                        "indexer": "Wire indexer",
                        "downloadUrl": "https://prowlarr.example.test/api/v1/download/1",
                    }
                ],
            )
        return httpx.Response(200, content=b"torrent-wire-bytes")

    native = HttpxProwlarrTransport(
        "https://prowlarr.example.test",
        "env:PROWLARR_API_KEY",
        lambda reference: {"env:PROWLARR_API_KEY": "prowlarr-secret"}[reference],
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    adapter = ProwlarrAdapter(native, SearchResultCache())
    result = adapter.search("Wire query", {"indexerIds": "4", "categories": "5000"})[0]
    resolved = adapter.resolve(result.token)

    assert isinstance(resolved.artifact, TorrentArtifact)
    assert resolved.artifact.content == b"torrent-wire-bytes"
    search = requests[0]
    assert search.url.params["query"] == "Wire query"
    assert search.url.params["type"] == "search"
    assert search.url.params["indexerIds"] == "4"
    assert search.url.params["categories"] == "5000"
    assert "prowlarr-secret" not in str(result)


def test_authenticated_torrent_resolution_rejects_every_cross_origin_variant(
    caplog: pytest.LogCaptureFixture,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=b"must-not-be-fetched")

    native = HttpxProwlarrTransport(
        "https://prowlarr.example.test:9696",
        "env:PROWLARR_API_KEY",
        lambda reference: "api-key-secret",
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    rejected = [
        "https://evil.example.test:9696/api/v1/download/passkey-secret",
        "http://prowlarr.example.test:9696/api/v1/download/1",
        "https://prowlarr.example.test/api/v1/download/1",
        "https://prowlarr.example.test:443/api/v1/download/1",
        "file://prowlarr.example.test:9696/api/v1/download/1",
        "https://user:password@prowlarr.example.test:9696/api/v1/download/1",
    ]

    for url in rejected:
        with pytest.raises(ProwlarrError) as error:
            native.fetch_torrent(url)
        assert str(error.value) == "prowlarr_download_origin_rejected"
        assert error.value.__cause__ is None

    assert requests == []
    assert "api-key-secret" not in caplog.text
    assert "passkey-secret" not in caplog.text
    assert "password" not in caplog.text


def test_snapshot_classification_ignores_upstream_safety_flags_and_paths() -> None:
    class FlagTransport(FakeProwlarrTransport):
        def search(self, query: str, filters: dict[str, str]) -> list[dict[str, object]]:
            return [
                {
                    "protocol": "torrent",
                    "title": "Flag fixture",
                    "indexer": "Indexer",
                    "magnetUrl": "magnet:?xt=urn:btih:" + "d" * 40,
                    "guid": "adapter.safe:opaque-42",
                    "guidIsPublic": False,
                    "infoUrl": "https://example.test/releases/42?session=secret#fragment",
                    "publicRoutePath": True,
                    "normalizedPublicPath": "/upstream-claims-safe/42",
                }
            ]

    result = ProwlarrAdapter(FlagTransport(), SearchResultCache()).search("Flag", {})[0]

    assert result.snapshot.guid == "adapter.safe:opaque-42"
    assert result.snapshot.source_page_url == "https://example.test"


def test_authenticated_resolution_never_follows_a_result_controlled_redirect() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "prowlarr.example.test":
            return httpx.Response(
                302,
                headers={"Location": "https://evil.example.test/passkey-secret"},
            )
        return httpx.Response(200, content=b"credential-leak")

    native = HttpxProwlarrTransport(
        "https://prowlarr.example.test",
        "env:PROWLARR_API_KEY",
        lambda reference: "api-key-secret",
        httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True),
    )

    with pytest.raises(ProwlarrError) as rejected:
        native.fetch_torrent("https://prowlarr.example.test/api/v1/download/1")

    assert str(rejected.value) == "prowlarr_download_failed"
    assert [request.url.host for request in requests] == ["prowlarr.example.test"]
