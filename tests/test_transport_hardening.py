import threading

import httpx
from media_finder.integration_runtime import DefaultRuntimeFactory
from media_finder.sdk.registration import (
    MetadataProviderRegistration,
    StaticModuleRegistry,
)
from media_finder_server import (
    create_legacy_module_registry,
    create_runtime_factory,
)
from pydantic import BaseModel

LEGACY_REGISTRY = create_legacy_module_registry()

ENVIRONMENT = {
    "TMDB_TOKEN": "tmdb-secret",
    "PROWLARR_URL": "https://services.example.test:9696/prowlarr",
    "PROWLARR_API_KEY": "prowlarr-secret",
    "QBITTORRENT_URL": "https://services.example.test:8080/qb",
    "QBITTORRENT_USERNAME": "operator",
    "QBITTORRENT_PASSWORD": "qb-secret",
}


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

    factory = create_runtime_factory(environment=ENVIRONMENT, http_client_factory=clients)
    provider = factory.metadata_provider("tmdb").value
    assert provider is not None
    assert factory.release_selections().value is not None
    client = factory.selected_download_client().value
    assert client is not None

    authentication_requests = [
        request for request in requests if request[2].endswith(("configuration", "status", "login"))
    ]
    assert len(created) == 3
    assert len({id(client) for client in created}) == 3
    assert all(cookie is None for _, _, _, cookie in authentication_requests)
    factory.close()


def test_runtime_closes_release_provider_through_its_owned_lifecycle() -> None:
    created: list[httpx.Client] = []

    def clients() -> httpx.Client:
        client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={})))
        created.append(client)
        return client

    factory = create_runtime_factory(environment=ENVIRONMENT, http_client_factory=clients)
    service = factory.release_selections().value
    assert service is not None
    assert len(created) == 1 and not created[0].is_closed

    factory.close()

    assert len(created) == 1 and created[0].is_closed


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
                retention_factory=lambda: LEGACY_REGISTRY.retention_providers()["manual"],
                build=fail_builder,
            )
        },
        download_clients={},
    )
    factory = DefaultRuntimeFactory(
        environment=ENVIRONMENT,
        http_client_factory=clients,
        registry=registry,
    )

    for _ in range(2):
        assert factory.metadata_provider("broken").error_code == (
            "metadata_provider_configuration_invalid"
        )

    assert len(created) == 2
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

    failed_factory = create_runtime_factory(
        environment=ENVIRONMENT, http_client_factory=failing_clients
    )
    for _ in range(2):
        assert (
            failed_factory.metadata_provider("tmdb").error_code
            == "metadata_provider_configuration_invalid"
        )
    for _ in range(2):
        assert (
            failed_factory.selected_download_client().error_code
            == "download_client_authentication_failed"
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

    success_factory = create_runtime_factory(
        environment=ENVIRONMENT, http_client_factory=mixed_clients
    )
    first_tmdb = success_factory.metadata_provider("tmdb").value
    assert first_tmdb is not None
    assert success_factory.metadata_provider("tmdb").value is first_tmdb
    first_qb = success_factory.selected_download_client().value
    assert first_qb is not None
    assert success_factory.selected_download_client().value is first_qb
    assert success_factory.release_selections().error_code == "prowlarr_configuration_invalid"
    assert len(retained) == 3
    assert not retained[0].is_closed and not retained[1].is_closed
    assert retained[2].is_closed
    assert success_factory._http_clients == []
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

    factory = create_runtime_factory(environment=ENVIRONMENT, http_client_factory=clients)
    failed_result: list[object] = []

    def fail_tmdb() -> None:
        failed_result.append(factory.metadata_provider("tmdb"))

    worker = threading.Thread(target=fail_tmdb)
    worker.start()
    assert tmdb_started.wait(timeout=5)
    successful = factory.selected_download_client().value
    assert successful is not None
    release_tmdb.set()
    worker.join(timeout=5)
    assert not worker.is_alive()

    assert len(failed_result) == 1
    assert failed_result[0].value is None
    assert len(created) == 2
    assert created[0].is_closed
    assert not created[1].is_closed
    assert factory.selected_download_client().value is successful
    assert factory._http_clients == []
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

    factory = create_runtime_factory(environment=ENVIRONMENT, http_client_factory=clients)
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
