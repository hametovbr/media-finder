import logging
import threading

import httpx
import pytest
from pydantic import BaseModel, ValidationError

from media_finder.models import DownloadClientInstance
from media_finder.modules.manual import ManualProvider
from media_finder.modules.qbittorrent import HttpxQbittorrentTransport, QbittorrentConfig
from media_finder.prowlarr import (
    ExpiredSearchToken,
    HttpxProwlarrTransport,
    ProwlarrAdapter,
    ProwlarrError,
    SearchResultCache,
)
from media_finder.sdk.registration import (
    DownloadClientRegistration,
    MetadataProviderRegistration,
    StaticModuleRegistry,
)
from media_finder.system_clients import SYSTEM_QBITTORRENT_ID
from media_finder.ui_runtime import DefaultRuntimeFactory


def _secrets(reference: str) -> str:
    return {
        "env:TMDB_TOKEN": "tmdb-secret",
        "env:PROWLARR_KEY": "prowlarr-secret",
        "env:QB_USER": "operator",
        "env:QB_PASS": "qb-secret",
    }[reference]


ENVIRONMENT = {
    "TMDB_TOKEN": "tmdb-secret",
    "PROWLARR_URL": "https://services.example.test:9696/prowlarr",
    "PROWLARR_API_KEY": "prowlarr-secret",
    "QBITTORRENT_URL": "https://services.example.test:8080/qb",
    "QBITTORRENT_USERNAME": "operator",
    "QBITTORRENT_PASSWORD": "qb-secret",
}


def system_client(module_key: str = "qbittorrent") -> DownloadClientInstance:
    return DownloadClientInstance(
        id=SYSTEM_QBITTORRENT_ID,
        name="qBittorrent",
        module_key=module_key,
        config_payload={},
        system_owned=True,
    )


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

    factory = DefaultRuntimeFactory(environment=ENVIRONMENT, http_client_factory=clients)
    provider = factory.metadata_provider("tmdb").value
    assert provider is not None
    assert factory.prowlarr().value is not None
    client = factory.download_client(system_client()).value
    assert client is not None

    authentication_requests = [
        request for request in requests if request[2].endswith(("configuration", "status", "login"))
    ]
    assert len(created) == 3
    assert len({id(client) for client in created}) == 3
    assert all(cookie is None for _, _, _, cookie in authentication_requests)
    factory.close()


class EmptyIntegrationConfig(BaseModel):
    pass


def test_failed_runtime_construction_closes_and_forgets_every_created_http_client() -> None:
    created: list[httpx.Client] = []

    def clients() -> httpx.Client:
        client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(500, json={})))
        created.append(client)
        return client

    def fail_builder(payload, http_client, secret_resolver):
        del payload, secret_resolver
        http_client()
        raise RuntimeError("construction failed")

    registry = StaticModuleRegistry(
        metadata_providers={
            "broken": MetadataProviderRegistration(
                key="broken",
                config_model=EmptyIntegrationConfig,
                retention_factory=ManualProvider,
                build=fail_builder,
            )
        },
        download_clients={
            "broken": DownloadClientRegistration(
                key="broken", config_model=EmptyIntegrationConfig, build=fail_builder
            )
        },
    )
    factory = DefaultRuntimeFactory(
        environment=ENVIRONMENT, http_client_factory=clients, registry=registry
    )

    for _ in range(2):
        assert factory.prowlarr().error_code == "prowlarr_configuration_invalid"
        assert factory.metadata_provider("broken").error_code == (
            "metadata_provider_configuration_invalid"
        )
        instance = system_client("broken")
        assert factory.download_client(instance).error_code == (
            "download_client_configuration_invalid"
        )

    assert len(created) == 6
    assert all(client.is_closed for client in created)
    assert factory._http_clients == []


def test_first_party_validation_owns_only_successful_cached_http_clients() -> None:
    failed: list[httpx.Client] = []

    def failing_clients() -> httpx.Client:
        client = httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    500 if request.url.host == "api.themoviedb.org" else 200,
                    text="Fails.",
                )
            )
        )
        failed.append(client)
        return client

    failed_factory = DefaultRuntimeFactory(
        environment=ENVIRONMENT, http_client_factory=failing_clients
    )
    for _ in range(2):
        assert (
            failed_factory.metadata_provider("tmdb").error_code
            == "metadata_provider_configuration_invalid"
        )
    for _ in range(2):
        instance = system_client()
        assert failed_factory.download_client(instance).error_code == (
            "download_client_configuration_invalid"
        )
    assert len(failed) == 4
    assert all(client.is_closed for client in failed)
    assert failed_factory._http_clients == []

    retained: list[httpx.Client] = []

    def mixed_clients() -> httpx.Client:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "services.example.test" and request.url.port == 9696:
                return httpx.Response(500, text="Fails.")
            if request.url.path.endswith("/api/v2/auth/login"):
                return httpx.Response(200, text="Ok.")
            return httpx.Response(200, json={})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        retained.append(client)
        return client

    success_factory = DefaultRuntimeFactory(
        environment=ENVIRONMENT, http_client_factory=mixed_clients
    )
    first_tmdb = success_factory.metadata_provider("tmdb").value
    assert first_tmdb is not None
    assert success_factory.metadata_provider("tmdb").value is first_tmdb
    good_instance = system_client()
    first_qb = success_factory.download_client(good_instance).value
    assert first_qb is not None
    assert success_factory.download_client(good_instance).value is first_qb
    assert success_factory.prowlarr().error_code == "prowlarr_configuration_invalid"
    assert len(retained) == 3
    assert not retained[0].is_closed and not retained[1].is_closed
    assert retained[2].is_closed
    assert success_factory._http_clients == retained[:2]
    success_factory.close()
    assert all(client.is_closed for client in retained)


def test_failed_interleaved_attempt_cannot_close_a_later_successful_client() -> None:
    tmdb_started = threading.Event()
    release_tmdb = threading.Event()
    created: list[httpx.Client] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.themoviedb.org":
            tmdb_started.set()
            assert release_tmdb.wait(timeout=5)
            return httpx.Response(500)
        if request.url.path.endswith("/api/v2/auth/login"):
            return httpx.Response(200, text="Ok.")
        return httpx.Response(200, json={})

    def clients() -> httpx.Client:
        client = httpx.Client(transport=httpx.MockTransport(handler))
        created.append(client)
        return client

    factory = DefaultRuntimeFactory(environment=ENVIRONMENT, http_client_factory=clients)
    failed_result: list[object] = []

    def fail_tmdb() -> None:
        failed_result.append(factory.metadata_provider("tmdb"))

    worker = threading.Thread(target=fail_tmdb)
    worker.start()
    assert tmdb_started.wait(timeout=5)
    instance = system_client()
    successful = factory.download_client(instance).value
    assert successful is not None
    release_tmdb.set()
    worker.join(timeout=5)
    assert not worker.is_alive()

    assert len(failed_result) == 1
    assert failed_result[0].value is None
    assert len(created) == 2
    assert created[0].is_closed
    assert not created[1].is_closed
    assert factory.download_client(instance).value is successful
    assert factory._http_clients == [created[1]]
    factory.close()
    assert created[1].is_closed


def test_factory_close_during_build_cannot_repopulate_caches_or_leak_client() -> None:
    request_started = threading.Event()
    release_request = threading.Event()
    created: list[httpx.Client] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.themoviedb.org"
        request_started.set()
        assert release_request.wait(timeout=5)
        return httpx.Response(200, json={})

    def clients() -> httpx.Client:
        client = httpx.Client(transport=httpx.MockTransport(handler))
        created.append(client)
        return client

    factory = DefaultRuntimeFactory(environment=ENVIRONMENT, http_client_factory=clients)
    results: list[object] = []
    worker = threading.Thread(target=lambda: results.append(factory.metadata_provider("tmdb")))
    worker.start()
    assert request_started.wait(timeout=5)

    factory.close()
    release_request.set()
    worker.join(timeout=5)

    assert not worker.is_alive()
    assert len(results) == 1
    assert results[0].value is None
    assert results[0].error_code == "integration_runtime_closed"
    assert len(created) == 1 and created[0].is_closed
    assert factory._http_clients == []
    assert factory._metadata == {}


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
