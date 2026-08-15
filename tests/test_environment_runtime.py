import httpx

from media_finder.models import DownloadClientInstance
from media_finder.system_clients import SYSTEM_QBITTORRENT_ID
from media_finder.ui_runtime import DefaultRuntimeFactory


def test_default_runtime_constructs_every_integration_only_from_exact_environment() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "api.themoviedb.org":
            assert request.headers["Authorization"] == "Bearer tmdb-from-environment"
            return httpx.Response(200, json={})
        if request.url.host == "prowlarr.example.test":
            assert request.headers["X-Api-Key"] == "prowlarr-from-environment"
            return httpx.Response(200, json={"version": "1"})
        if request.url.host == "qb.example.test":
            if request.url.path == "/api/v2/auth/login":
                assert b"username=environment-user" in request.content
                assert b"password=environment-password" in request.content
                return httpx.Response(200, text="Ok.")
            return httpx.Response(200, json={})
        return httpx.Response(404)

    factory = DefaultRuntimeFactory(
        environment={
            "TMDB_TOKEN": "tmdb-from-environment",
            "PROWLARR_URL": "https://prowlarr.example.test",
            "PROWLARR_API_KEY": "prowlarr-from-environment",
            "QBITTORRENT_URL": "https://qb.example.test",
            "QBITTORRENT_USERNAME": "environment-user",
            "QBITTORRENT_PASSWORD": "environment-password",
        },
        http_client_factory=lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )
    system = DownloadClientInstance(
        id=SYSTEM_QBITTORRENT_ID,
        name="qBittorrent",
        module_key="qbittorrent",
        system_owned=True,
        config_payload={
            "base_url": "https://attacker.example.test",
            "username_ref": "env:ATTACKER_USER",
            "password_ref": "env:ATTACKER_PASSWORD",
        },
    )

    assert factory.metadata_provider("tmdb").value is not None
    assert factory.prowlarr().value is not None
    assert factory.download_client(system).value is not None
    assert {request.url.host for request in requests} == {
        "api.themoviedb.org",
        "prowlarr.example.test",
        "qb.example.test",
    }


def test_missing_environment_returns_safe_exact_names_without_values() -> None:
    factory = DefaultRuntimeFactory(environment={"TMDB_TOKEN": ""})

    tmdb = factory.metadata_provider("tmdb")
    prowlarr = factory.prowlarr()
    qbittorrent = factory.download_client(
        DownloadClientInstance(
            id=SYSTEM_QBITTORRENT_ID,
            name="qBittorrent",
            module_key="qbittorrent",
            config_payload={},
            system_owned=True,
        )
    )

    assert tmdb.error_code == "integration_environment_missing"
    assert tmdb.missing_variables == ("TMDB_TOKEN",)
    assert prowlarr.error_code == "integration_environment_missing"
    assert prowlarr.missing_variables == ("PROWLARR_URL", "PROWLARR_API_KEY")
    assert qbittorrent.error_code == "integration_environment_missing"
    assert qbittorrent.missing_variables == (
        "QBITTORRENT_URL",
        "QBITTORRENT_USERNAME",
        "QBITTORRENT_PASSWORD",
    )
    assert "TMDB_TOKEN" in repr(tmdb)
    assert "tmdb-from-environment" not in repr(tmdb)
