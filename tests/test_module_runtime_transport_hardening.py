"""Concurrency and HTTP ownership at the public production module boundary."""

from __future__ import annotations

from threading import Event, Thread

import httpx
import pytest
from media_finder_core.acquisition import ReleaseSelectionCache
from media_finder_sdk import ModuleError
from media_finder_server.modules import create_runtime_module_composition

ENVIRONMENT = {
    "TMDB_TOKEN": "tmdb-secret",
    "PROWLARR_URL": "https://services.example.test:9696/prowlarr",
    "PROWLARR_API_KEY": "prowlarr-secret",
    "QBITTORRENT_URL": "https://services.example.test:8080/qb",
    "QBITTORRENT_USERNAME": "operator",
    "QBITTORRENT_PASSWORD": "qb-secret",
}


def test_production_composition_isolates_authenticated_sessions_across_module_kinds() -> None:
    requests: list[tuple[str, int | None, str, str | None]] = []
    created: list[httpx.Client] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(
            (request.url.host, request.url.port, request.url.path, request.headers.get("cookie"))
        )
        if request.url.path.endswith("/configuration"):
            return httpx.Response(200, json={}, headers={"set-cookie": "TMDB=metadata; Path=/"})
        if request.url.path.endswith("/api/v1/system/status"):
            return httpx.Response(200, json={}, headers={"set-cookie": "PROWLARR=release; Path=/"})
        if request.url.path.endswith("/api/v2/auth/login"):
            return httpx.Response(200, text="Ok.", headers={"set-cookie": "SID=download; Path=/"})
        return httpx.Response(200, json={})

    def clients() -> httpx.Client:
        client = httpx.Client(transport=httpx.MockTransport(handler))
        created.append(client)
        return client

    composition = create_runtime_module_composition(
        environment=ENVIRONMENT,
        release_cache=ReleaseSelectionCache(),
        client_factory=clients,
    )
    runtime = composition.runtime
    try:
        assert runtime.metadata_provider("tmdb") is runtime.metadata_provider("tmdb")
        assert runtime.release_provider("prowlarr") is runtime.release_provider("prowlarr")
        assert runtime.download_client("qbittorrent") is runtime.download_client("qbittorrent")

        authentication_requests = [
            request
            for request in requests
            if request[2].endswith(("configuration", "status", "login"))
        ]
        assert len(created) == 3
        assert len({id(client) for client in created}) == 3
        assert len({id(client.cookies) for client in created}) == 3
        assert all(cookie is None for _, _, _, cookie in authentication_requests)
        assert [set(client.cookies.keys()) for client in created] == [
            {"TMDB"},
            {"PROWLARR"},
            {"SID"},
        ]
    finally:
        composition.release_selections.close()
        runtime.close()

    assert all(client.is_closed for client in created)


def test_failed_construction_interleaved_with_successful_sibling_is_attempt_local() -> None:
    tmdb_started = Event()
    release_tmdb = Event()
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

    composition = create_runtime_module_composition(
        environment=ENVIRONMENT,
        release_cache=ReleaseSelectionCache(),
        client_factory=clients,
    )
    runtime = composition.runtime
    failures: list[ModuleError] = []

    def fail_tmdb() -> None:
        try:
            runtime.metadata_provider("tmdb")
        except ModuleError as error:
            failures.append(error)

    worker = Thread(target=fail_tmdb)
    worker.start()
    assert tmdb_started.wait(timeout=5)
    successful = runtime.download_client("qbittorrent")
    release_tmdb.set()
    worker.join(timeout=5)

    try:
        assert not worker.is_alive()
        assert [error.code for error in failures] == ["metadata_provider_unavailable"]
        assert len(created) == 2
        assert created[0].is_closed
        assert not created[1].is_closed
        assert runtime.download_client("qbittorrent") is successful
    finally:
        composition.release_selections.close()
        runtime.close()

    assert created[1].is_closed


def test_runtime_close_racing_in_progress_build_cannot_repopulate_or_leak() -> None:
    request_started = Event()
    release_request = Event()
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

    composition = create_runtime_module_composition(
        environment=ENVIRONMENT,
        release_cache=ReleaseSelectionCache(),
        client_factory=clients,
    )
    runtime = composition.runtime
    failures: list[ModuleError] = []

    def build_tmdb() -> None:
        try:
            runtime.metadata_provider("tmdb")
        except ModuleError as error:
            failures.append(error)

    worker = Thread(target=build_tmdb)
    worker.start()
    assert request_started.wait(timeout=5)
    runtime.close()
    release_request.set()
    worker.join(timeout=5)
    composition.release_selections.close()

    assert not worker.is_alive()
    assert [error.code for error in failures] == ["module_runtime_closed"]
    assert len(created) == 1 and created[0].is_closed
    with pytest.raises(ModuleError, match="module_runtime_closed"):
        runtime.metadata_provider("tmdb")
