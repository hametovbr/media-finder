import logging

import httpx
import pytest
from pydantic import ValidationError

from media_finder.models import DownloadClientInstance
from media_finder.modules.qbittorrent import HttpxQbittorrentTransport, QbittorrentConfig
from media_finder.prowlarr import (
    ExpiredSearchToken,
    HttpxProwlarrTransport,
    ProwlarrAdapter,
    ProwlarrError,
    SearchResultCache,
)
from media_finder.ui_runtime import DefaultRuntimeFactory


def _secrets(reference: str) -> str:
    return {
        "env:TMDB_TOKEN": "tmdb-secret",
        "env:PROWLARR_KEY": "prowlarr-secret",
        "env:QB_USER": "operator",
        "env:QB_PASS": "qb-secret",
    }[reference]


def test_integration_base_urls_reject_secret_components_but_allow_safe_subpaths() -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={})))
    unsafe = (
        "https://user:password@services.example.test/app",
        "https://services.example.test/app?token=secret",
        "https://services.example.test/app#fragment",
        "https://services.example.test/passkey/value",
        "https://services.example.test/service/%73ecret",
    )
    for value in unsafe:
        with pytest.raises(ValueError, match="prowlarr_base_url_invalid"):
            HttpxProwlarrTransport(value, "env:PROWLARR_KEY", _secrets, client)
        with pytest.raises(ValidationError):
            QbittorrentConfig(
                base_url=value,
                username_ref="env:QB_USER",
                password_ref="env:QB_PASS",
            )
        with pytest.raises(ValueError, match="qbittorrent_base_url_invalid"):
            HttpxQbittorrentTransport(value, client)

    prowlarr = HttpxProwlarrTransport(
        "https://services.example.test/apps/prowlarr",
        "env:PROWLARR_KEY",
        _secrets,
        client,
    )
    qb = HttpxQbittorrentTransport("https://services.example.test/apps/qb", client)
    assert prowlarr is not None and qb is not None


def test_runtime_http_sessions_are_isolated_per_service_and_qb_instance() -> None:
    requests: list[tuple[str, int | None, str, str | None]] = []
    created: list[httpx.Client] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(
            (request.url.host, request.url.port, request.url.path, request.headers.get("cookie"))
        )
        if request.url.path.endswith("/configuration"):
            return httpx.Response(200, json={}, headers={"set-cookie": "SID=tmdb; Path=/"})
        if request.url.path.endswith("/api/v1/system/status"):
            return httpx.Response(200, json={}, headers={"set-cookie": "SID=prowlarr; Path=/"})
        if request.url.path.endswith("/api/v2/auth/login"):
            return httpx.Response(200, text="Ok.", headers={"set-cookie": "SID=qb; Path=/"})
        return httpx.Response(200, json={})

    def clients() -> httpx.Client:
        client = httpx.Client(transport=httpx.MockTransport(handler))
        created.append(client)
        return client

    factory = DefaultRuntimeFactory(http_client_factory=clients, secret_resolver=_secrets)
    provider = factory.metadata_provider(
        "tmdb",
        {
            "api_token": "env:TMDB_TOKEN",
            "base_url": "https://services.example.test:8443/tmdb/3",
        },
    ).value
    assert provider is not None
    provider.validate_config()
    assert (
        factory.prowlarr(
            {
                "base_url": "https://services.example.test:9696/prowlarr",
                "api_key_ref": "env:PROWLARR_KEY",
            }
        ).value
        is not None
    )

    for instance_id, port in (("q1", 8080), ("q2", 8081)):
        instance = DownloadClientInstance(
            id=instance_id,
            name=instance_id,
            module_key="qbittorrent",
            config_payload={
                "base_url": f"https://services.example.test:{port}/qb",
                "username_ref": "env:QB_USER",
                "password_ref": "env:QB_PASS",
            },
        )
        client = factory.download_client(instance).value
        assert client is not None
        client.validate_config()

    authentication_requests = [
        request for request in requests if request[2].endswith(("configuration", "status", "login"))
    ]
    assert len(created) == 4
    assert len({id(client) for client in created}) == 4
    assert all(cookie is None for _, _, _, cookie in authentication_requests)
    factory.close()


def test_prowlarr_bounds_json_result_count_and_torrent_bytes_with_one_use_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/v1/search"):
            mode = request.url.params.get("query")
            if mode == "large-json":
                return httpx.Response(200, content=b"[" + b" " * 300 + b"]")
            if mode == "many-results":
                return httpx.Response(200, json=[{"protocol": "torrent"}] * 3)
            return httpx.Response(
                200,
                json=[
                    {
                        "protocol": "torrent",
                        "title": "Oversized artifact",
                        "indexer": "Fixture",
                        "downloadUrl": "https://services.example.test/prowlarr/download/passkey-value",
                    }
                ],
            )
        return httpx.Response(200, content=b"x" * 17)

    transport = HttpxProwlarrTransport(
        "https://services.example.test/prowlarr",
        "env:PROWLARR_KEY",
        _secrets,
        httpx.Client(transport=httpx.MockTransport(handler)),
        max_json_bytes=256,
        max_search_results=2,
        max_torrent_bytes=16,
    )
    with pytest.raises(ProwlarrError, match="prowlarr_response_too_large"):
        transport.search("large-json", {})
    with pytest.raises(ProwlarrError, match="prowlarr_result_limit_exceeded"):
        transport.search("many-results", {})

    adapter = ProwlarrAdapter(transport, SearchResultCache())
    token = adapter.search("torrent", {})[0].token
    with pytest.raises(ProwlarrError, match="prowlarr_torrent_too_large"):
        adapter.resolve(token)
    with pytest.raises(ExpiredSearchToken):
        adapter.resolve(token)


def test_httpx_logging_never_contains_complete_prowlarr_download_url_or_passkey(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_url = "https://services.example.test/prowlarr/download/passkey-value?auth=never-log"
    client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(500)))
    transport = HttpxProwlarrTransport(
        "https://services.example.test/prowlarr", "env:PROWLARR_KEY", _secrets, client
    )
    caplog.set_level(logging.DEBUG, logger="httpx")

    with pytest.raises(ProwlarrError):
        transport.fetch_torrent(secret_url)

    rendered = "\n".join(record.getMessage() for record in caplog.records)
    assert secret_url not in rendered
    assert "passkey-value" not in rendered
    assert "never-log" not in rendered
