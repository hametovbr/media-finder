import httpx
from media_finder_server import create_runtime_factory


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

    factory = create_runtime_factory(
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
    assert factory.metadata_provider("tmdb").value is not None
    assert factory.release_selections().value is not None
    assert factory.selected_download_client().value is not None
    assert {request.url.host for request in requests} == {
        "api.themoviedb.org",
        "prowlarr.example.test",
        "qb.example.test",
    }


def test_missing_environment_returns_safe_exact_names_without_values() -> None:
    factory = create_runtime_factory(environment={"TMDB_TOKEN": ""})

    tmdb = factory.metadata_provider("tmdb")
    release = factory.release_selections()
    download = factory.selected_download_client()

    assert tmdb.error_code == "integration_environment_missing"
    assert tmdb.missing_variables == ("TMDB_TOKEN",)
    assert release.error_code == "module_environment_missing"
    assert release.missing_variables == ("PROWLARR_URL", "PROWLARR_API_KEY")
    assert download.error_code == "module_environment_missing"
    assert download.missing_variables == (
        "QBITTORRENT_URL",
        "QBITTORRENT_USERNAME",
        "QBITTORRENT_PASSWORD",
    )
    assert "TMDB_TOKEN" in repr(tmdb)
    assert "tmdb-from-environment" not in repr(tmdb)
